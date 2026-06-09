# Kaika 開花 — Spécification

*Spécification v0.2 · projet personnel*

**Auteur :** Florent Lejoly · **Date :** 09 juin 2026 · **Statut :** draft, à challenger

Une application complète qui transforme un morceau de musique en clip vidéo : une simulation de fluides dansée par l'analyse du son, métamorphosée en formes vivantes par un modèle de diffusion vidéo, le tout piloté depuis une interface locale et lancé en une seule commande.

> *Le pipeline : une onde sonore devient turbulence fluide puis fleurs — du son, un fluide ; du fluide, une fleur.*

## Sommaire

01. [Vision et objectifs](#01--vision-et-objectifs)
02. [Architecture générale](#02--architecture-générale)
03. [Les cinq étages](#03--les-cinq-étages)
04. [Le format recette](#04--le-format-recette)
05. [L'application](#05--lapplication)
06. [Stack et structure du repo](#06--stack-et-structure-du-repo)
07. [Jalons](#07--jalons)
08. [Risques et inconnues](#08--risques-et-inconnues)
09. [Questions ouvertes](#09--questions-ouvertes)

---

## 01 · Vision et objectifs

**Kaika** (開花, « éclosion, floraison ») est une application locale qui prend un fichier audio et produit un clip vidéo où l'image ne réagit pas à la musique : elle la *danse*. Le système connaît tout le morceau à l'avance, donc le visuel peut anticiper, des bourgeons se forment avant le drop et éclosent dessus.

Le principe central : une simulation de fluides sert de **squelette de mouvement**. Elle n'est pas l'image finale, elle est la partition gestuelle qu'un modèle de diffusion vidéo habille ensuite de formes figuratives (fleurs, organismes, matières) tout en respectant sa structure et son flux.

Kaika est une **app complète**, pas une collection de scripts : une seule commande la lance, et tout le travail créatif (charger un morceau, composer une recette, itérer, suivre un rendu, revoir ses clips) se fait dans une interface agréable. Le terminal sert à démarrer, jamais à créer.

### Objectifs

- **Une seule commande** : `kaika` démarre tout (serveur + interface) et ouvre le navigateur. Zéro configuration pour le cas nominal.
- **Une interface agréable** : tout le flux créatif passe par l'UI ; aucune option indispensable n'est cachée dans un terminal ou un fichier à éditer à la main (le YAML reste accessible pour les power users, mais jamais obligatoire).
- Pipeline reproductible : un morceau + une recette de style → un clip, rejouable à l'identique.
- Synchronisation à la frame près, avec anticipation des événements musicaux.
- Des événements visuels qui « popent » de partout, pilotés par les onsets, pas seulement une masse centrale.
- Chaque étage testable et regardable isolément (la vidéo de fluide brute doit déjà être belle).
- Coût marginal faible : itération locale, GPU loué uniquement pour l'étage diffusion.

### Non-objectifs (v1)

- Temps réel et performance live (explicitement hors scope, peut devenir une v2).
- Multi-utilisateurs, déploiement cloud public, comptes : Kaika est une app locale, mono-utilisateur.
- Édition vidéo généraliste (montage, cuts) : Kaika produit un clip, il ne remplace pas un éditeur.
- Génération de la musique elle-même.

---

## 02 · Architecture générale

Le cœur est un pipeline de cinq étages en chaîne, chacun avec des entrées/sorties sur disque (frames PNG, JSON, MP4). Aucun étage ne connaît l'implémentation des autres : on peut remplacer la sim de fluide ou le modèle de diffusion sans toucher au reste. Autour de ce cœur, une application locale (serveur + interface web, section 05) orchestre les rendus ; l'UI et la CLI appellent exactement la même librairie.

```
# flux de données
track.wav
   │
   ▼
E1 analyse      librosa ──────────────▶ score.json
   │
   ▼
E2 simulation   fluide piloté ────────▶ fluid/%06d.png
   │
   ▼
E3 contrôle     densité + vélocité ───▶ control/{depth,canny,flow}/
   │
   ▼
E4 diffusion    vid2vid (GPU loué) ───▶ styled/%06d.png
   │
   ▼
E5 post         RIFE + upscale + mux ─▶ kaika_final.mp4
```

> **Décision structurante.** La frontière entre E3 et E4 est l'interface la plus importante du projet : « frames de contrôle en entrée, frames stylisées en sortie ». Les modèles vid2vid évoluent tous les trois mois ; tant que cette interface tient, E4 est remplaçable sans douleur.

---

## 03 · Les cinq étages

### E1 · Analyse audio — Le morceau devient une partition machine

**in** `track.wav` / `track.mp3` · **out** `score.json`

Analyse hors-ligne complète avec `librosa`. Le `hop_length` doit être un entier calé au plus près du framerate vidéo cible (`hop = int(round(sr / fps))`) pour que chaque frame vidéo ait sa ligne de données audio, sans interpolation. Attention aux couples `sr`/`fps` qui ne se divisent pas exactement (ex. 44100 Hz / 24 fps = 1837,5) : l'arrondi cumule une dérive temporelle au fil du morceau. Mitigation : imposer un ré-échantillonnage vers un couple compatible (48000 Hz / 24 fps → hop exact de 2000), ou compenser la dérive en ré-alignant périodiquement l'index de frame sur le temps réel.

| Signal | Méthode | Usage en aval |
| --- | --- | --- |
| tempo + beat grid | beat_track | pulsation de base, respiration du fluide |
| onsets par bande | flux spectral sur 3 bandes (low < 150 Hz, mid, high > 4 kHz) | déclencheurs de splats : kick = gros splat, hats = petits pops partout |
| énergie (RMS) | par frame | vorticité, vitesse globale, intensité lumineuse |
| centroïde spectral | par frame | teinte / température de couleur |
| sections | segmentation structurelle + heuristiques d'énergie | changements de prompt et de palette, anticipation des drops |

```jsonc
// score.json (extrait)
{
  "audio": { "sr": 44100, "duration_s": 192.4, "fps": 24 },
  "tempo_bpm": 128.0,
  "beats": [ { "t": 0.468, "strength": 0.82 }, … ],
  "onsets": { "low": [ { "t": 0.47, "mag": 0.9 }, … ], "mid": […], "high": […] },
  "frames": [ { "rms": 0.31, "centroid_hz": 1840, "bands": [0.6, 0.3, 0.1] }, … ],
  "sections": [
    { "start": 0.0, "end": 30.7, "label": "intro", "energy": 0.25 },
    { "start": 61.4, "end": 92.1, "label": "drop", "energy": 0.95 }, …
  ]
}
```

**Done quand :** un script de debug superpose beats, onsets et sections sur la waveform et que ça colle à l'oreille.

### E2 · Simulation fluide — Le squelette de mouvement

**in** `score.json` + recette · **out** `fluid/%06d.png` + `velocity/%06d.npy`

Stable fluids (Navier-Stokes incompressible à la Jos Stam) implémenté en Python avec **Taichi** pour le GPU. Choix assumé contre le fork WebGL : déterminisme total (seed → même vidéo), résolution libre, et l'accès direct aux champs internes (densité, vélocité) dont E3 a besoin. C'est le même territoire que Fractaquin : Python, frames, ffmpeg.

Grille de simulation 512×512 ou 768×768, rendu upsamplé en 1024×1024 (les modèles vidéo travaillent bien en carré ; le format final se décide en E5).

#### Mapping audio → fluide

| Événement | Effet |
| --- | --- |
| onset low (kick) | splat large et lent, position semi-stable (centre de gravité de la composition) |
| onset high (hats, percs) | petits splats vifs à positions aléatoires seedées : le « pop de partout » |
| rms continu | module vorticity confinement et dissipation : musique calme = fluide qui s'étire, drop = turbulence dense |
| centroïde | palette de couleur de la densité injectée |
| section à venir | **lookahead** : N secondes avant un drop, injection progressive de vortex sous le seuil de visibilité, la tension se construit dans l'image avant d'éclater dans le son |

**Done quand :** la vidéo de fluide seule, avec l'audio, est déjà un objet regardable et publiable (candidat naturel pour USELESS).

### E3 · Signaux de contrôle — L'avantage déloyal de la simulation

**in** `fluid/` + `velocity/` · **out** `control/depth/` · `control/canny/` · `control/flow/`

Point clé : contrairement à une vidéo filmée, on ne doit *rien estimer*. La sim fournit la vérité terrain.

- **Pseudo-depth** : le champ de densité du fluide, normalisé, sert directement de depth map. Zéro modèle d'estimation, zéro bruit.
- **Canny** : contours extraits de la densité (OpenCV), pour les recettes qui veulent des structures nettes.
- **Optical flow exact** : le champ de vélocité de la sim, exporté tel quel. Les modèles contrôlés par flow reçoivent un signal parfait, ce qui aide énormément la cohérence du mouvement.

**Done quand :** les trois sorties se visualisent proprement et restent alignées frame à frame avec la vidéo de fluide.

### E4 · Métamorphose (vid2vid) — Le fluide devient fleur

**in** `fluid/` + `control/` + prompt schedule · **out** `styled/%06d.png`

Transformation vid2vid dans **ComfyUI**, modèle de départ **Wan 2.2** (famille VACE / contrôle vidéo), exécuté sur GPU loué. Le workflow ComfyUI est versionné dans le repo comme un artefact de code.

- **Chunks avec recouvrement** : le morceau est découpé en segments de ~5 s avec un overlap de quelques dizaines de frames, fondus entre eux. Les coupes de chunks sont alignées sur les frontières de sections musicales quand c'est possible : une couture sur un drop se voit moins qu'une couture au milieu d'une nappe.
- **Denoise strength 0.4 à 0.6** : assez bas pour respecter la structure du fluide, assez haut pour faire émerger les formes figuratives. C'est LE paramètre esthétique du projet.
- **Prompt schedule auto-générée** depuis `score.json` + recette : chaque section musicale mappe vers un prompt (« bourgeons sombres, macro » sur l'intro, « éclosion massive de pivoines, pétales en suspension » sur le drop).
- **Seed fixe** par rendu, pour la reproductibilité et la comparaison d'itérations.

**Infra** : GPU loué à l'heure (Vast.ai / RunPod, RTX 5090 ou A100 selon la taille du modèle), provisionné par un script (image Docker avec ComfyUI + modèles, montage du dossier `control/`, rendu, rapatriement). Ordre de grandeur attendu : quelques heures de GPU par clip de 3 minutes, soit quelques euros par rendu complet. Toutes les itérations esthétiques se font sur des extraits de 10 s.

**Transfert** : un clip de 3 min à 24 fps = ~4300 frames × plusieurs flux (depth, canny, flow + frames stylisées en retour), soit plusieurs Go de PNG individuels — goulot d'étranglement majeur sur une connexion domestique. On ne transfère donc jamais les frames une à une : chaque séquence de contrôle est encodée dans un conteneur vidéo temporaire à haut débit (H.264/HEVC quasi-sans perte, `-crf` bas, YUV444p quand le contrôle l'exige) avant upload, ré-extraite côté GPU, puis le résultat est ré-encodé en vidéo pour le rapatriement. La compression réduit drastiquement la taille et le temps de transfert.

**Validation rapide avant d'investir** : passer un extrait de fluide dans un outil commercial de restyle (Runway) pour valider que l'esthétique fluide→fleurs fonctionne, avant de monter le workflow open source.

**Done quand :** un extrait de 10 s tient visuellement : les fleurs suivent le mouvement du fluide, les coutures de chunks sont invisibles à vitesse réelle.

### E5 · Post-production — Assemblage final

**in** `styled/` + `track.wav` · **out** `kaika_final.mp4`

- **Interpolation RIFE** si E4 a généré à 12 ou 16 fps (économie de GPU) : remontée à 24 ou 48 fps.
- **Upscale** Real-ESRGAN ou équivalent vers 2048², puis crop/letterbox vers le format de diffusion (carré pour Instagram, 16:9 sinon).
- **Mux ffmpeg** de l'audio original, avec vérification automatique de l'offset. La corrélation se fait entre l'enveloppe RMS de l'audio et l'énergie cinétique (ou la densité globale) de la simulation de fluide E2 — signal directement et déterministement piloté par l'audio — et non avec la luminance des frames stylisées, qui dépend trop du prompt et de la palette (un drop intense peut être visuellement sombre). Si la sync dérive, ça se mesure de façon fiable.
- Optionnel : grain léger et vignettage pour fondre les artefacts de diffusion.

---

## 04 · Le format recette

Une **recette** est un fichier YAML qui définit entièrement l'identité visuelle d'un rendu : mapping audio→fluide, palette, prompts par type de section, paramètres de diffusion. Un morceau + deux recettes = deux clips radicalement différents. C'est le levier créatif du projet.

```yaml
# recipes/eclosion.yaml
name: eclosion
seed: 4217

fluid:
  resolution: 768
  splats:
    low:  { radius: 0.12, force: 9000, placement: anchored }
    high: { radius: 0.03, force: 3500, placement: scatter, max_per_beat: 5 }
  vorticity: { min: 8, max: 38, driver: rms }
  lookahead_s: 8.0

diffusion:
  model: wan-2.2-vace
  strength: 0.5
  control: [depth, flow]
  chunk_s: 5.0
  overlap_frames: 24

prompts:
  base: "macro photography, botanical, dark background, soft light"  # modificateur global, préfixé à chaque section
  intro: "closed flower buds emerging from black water, mist"
  build: "buds swelling, petals straining, tension"
  drop:  "explosive bloom of peonies, petals suspended mid-air"
  outro: "petals dissolving back into dark water"
  default: "botanical organic forms, abstract motion"  # repli si le label de section est inconnu
```

Le prompt effectif d'une section est `"{base}, {section}"` ; `base` est donc systématiquement préfixé. Si le label d'une section détectée dans `score.json` (ex. `verse`) n'a pas de clé dédiée, on retombe sur `default` — le pipeline ne casse jamais sur un label imprévu.

---

## 05 · L'application

### Une seule commande

`kaika` (installé via `uv tool install kaika`, ou directement `uvx kaika` sans installation) démarre le serveur FastAPI, sert le frontend pré-compilé embarqué dans le package, et ouvre le navigateur sur `localhost:8400`. Pas de npm au runtime, pas de base de données à installer (SQLite embarqué), pas de fichier de config obligatoire. Une image Docker équivalente existe pour qui préfère (`docker run -p 8400:8400 kaika`).

> **Principe.** Le terminal sert à démarrer l'app, jamais à créer. Toute la création passe par l'interface. La CLI avancée (`kaika run track.wav --recipe eclosion`) existe pour le scripting et la CI, mais c'est un second citoyen : elle appelle la même librairie que l'UI, jamais l'inverse.

### Backend

- **FastAPI + WebSockets** : les rendus sont des jobs asynchrones ; la progression (étage courant, frame courante, aperçus intermédiaires, logs) est poussée en temps réel vers l'interface.
- **File de jobs simple** : un rendu à la fois en local (la sim sature déjà le GPU/CPU), avec file d'attente. L'étage E4 peut tourner sur GPU distant pendant qu'un autre job fait sa sim en local.
- **Tout est un run** : chaque lancement écrit `runs/<id>/` avec la recette gelée, le score, les sorties intermédiaires et le clip final. L'UI ne montre rien qui ne soit pas rejouable.

### Interface : trois écrans

**1 · Studio.** L'écran de création. On glisse un fichier audio, la waveform s'affiche annotée (beats, onsets, sections détectées). Les sections sont *éditables à la souris* : déplacer une frontière, renommer un label, c'est la correction directe de score.json sans jamais le voir. À droite, la recette : un formulaire structuré (sliders pour strength, vorticité, lookahead ; champs de prompt par section) avec un onglet YAML brut synchronisé pour les réglages fins. En bas, le geste central de l'app : **sélectionner un extrait de 10 s sur la waveform et lancer un rendu partiel**, parce que toute l'itération esthétique se joue là, à coût GPU minimal.

**2 · Rendu.** Le pipeline visualisé : les cinq étages en ligne, chacun avec son état (en attente, en cours avec pourcentage, terminé), les logs repliables, et surtout des aperçus dès qu'ils existent : la vidéo de fluide se regarde pendant que la diffusion tourne encore. Un rendu raté s'identifie en 30 secondes, pas à la fin.

**3 · Galerie.** Tous les runs, filtrables par morceau et par recette. Chaque run : lecteur vidéo, recette gelée consultable, et deux actions : *relancer avec variation* (ouvre le Studio pré-rempli avec cette config) et *comparer* (deux rendus côte à côte, synchronisés sur la même timeline audio, pour juger un changement de paramètre).

### Principes UX

- L'itération sur extrait est le chemin par défaut ; le rendu complet est l'aboutissement, pas le point de départ.
- Aucun état caché : ce que montre l'UI est ce qu'il y a sur disque dans `runs/`.
- Les erreurs disent quoi faire (« le GPU distant n'a pas répondu, vérifie le provisioning dans Réglages »), pas seulement ce qui a cassé.
- L'app doit être agréable au sens plein : soignée visuellement, réactive, à la hauteur de l'objet qu'elle fabrique.

---

## 06 · Stack et structure du repo

| Domaine | Choix | Pourquoi |
| --- | --- | --- |
| langage | Python 3.12 | terrain connu, écosystème audio/vision |
| app backend | FastAPI, uvicorn, WebSockets, SQLite | même stack que LLM Arena et Statisfaction, jobs asynchrones avec progression temps réel |
| frontend | React + Vite + TypeScript | stack du site perso, compilé puis embarqué dans le package Python (aucun npm au runtime) |
| packaging | uv, une commande : `uvx kaika` | installation et lancement en un geste ; image Docker en alternative |
| audio | librosa, soundfile | standard de fait, analyse complète hors-ligne |
| simulation | Taichi | GPU sans CUDA bas niveau, tourne aussi sur Metal (le futur MacBook fera tourner toute l'app sauf E4) |
| vision | OpenCV, NumPy | canny, normalisations, visualisations debug |
| diffusion | ComfyUI + Wan 2.2, Docker, GPU loué | seul étage qui exige du gros GPU NVIDIA, donc isolé et loué à l'heure |
| assemblage | ffmpeg, RIFE, Real-ESRGAN | déjà maîtrisé via Fractaquin et les vidéos mensuelles |

```
kaika/
├── recipes/              # YAML, identités visuelles
├── kaika/
│   ├── core/             # la librairie : E1 à E5, appelée par l'UI et la CLI
│   │   ├── analyze.py    # E1 : wav → score.json
│   │   ├── simulate.py   # E2 : score + recette → frames fluide
│   │   ├── control.py    # E3 : depth / canny / flow
│   │   ├── diffuse/      # E4 : workflow ComfyUI + provision GPU
│   │   └── post.py       # E5 : RIFE, upscale, mux
│   ├── server/           # FastAPI : API, WebSockets, file de jobs
│   ├── webapp_dist/      # frontend compilé, embarqué dans le package
│   └── cli.py            # kaika (lance l'app) · kaika run … (scripting)
├── webapp/               # sources React/Vite/TS du frontend
└── runs/                 # un dossier par rendu, config gelée + outputs
```

Chaque rendu écrit dans `runs/<timestamp>/` une copie gelée de la recette et du score : n'importe quel clip est re-générable à l'identique.

---

## 07 · Jalons

**M0 — Partition.** E1 complet + visualisation debug (waveform annotée beats/onsets/sections).
*done : les annotations collent à l'oreille sur 3 morceaux de styles différents · ~1 à 2 soirées*

**M1 — Danse abstraite.** E2 + E5 minimal : un clip complet de fluide synchronisé, avec lookahead. Livrable autonome, publiable sur USELESS même si la suite n'aboutit jamais.
*done : un clip de 3 min qui donne envie d'être regardé deux fois · ~3 à 5 soirées*

**M2 — Preuve d'éclosion.** E3 + E4 sur un extrait de 10 s. D'abord un test Runway pour valider l'esthétique, puis le workflow ComfyUI/Wan sur GPU loué.
*done : les fleurs suivent le fluide de façon convaincante sur 10 s · le risque principal du projet tombe ici*

**M3 — App v1.** Le serveur, l'écran Studio (waveform, recette, extrait de 10 s) et l'écran Rendu, branchés sur le pipeline complet. Une commande lance tout.
*done : uvx kaika ouvre l'app ; un morceau glissé dans le Studio ressort en clip complet sans toucher au terminal*

**M4 — Itération confortable.** La Galerie, la comparaison côte à côte, le « relancer avec variation », l'édition des sections à la souris. C'est le jalon qui rend l'app agréable, pas seulement fonctionnelle.
*done : une session d'une heure dans l'app sans ouvrir un seul fichier à la main*

**M5 — Recettes.** 2 à 3 identités visuelles distinctes, raffinement de l'anticipation, exploration (encre, bioluminescence, croissance minérale…).
*ouvert, c'est la partie jardin*

---

## 08 · Risques et inconnues

| Risque | Gravité | Mitigation |
| --- | --- | --- |
| coutures entre chunks visibles (sauts de contenu) | haute | overlap + blending latent, seed fixe, coutures alignées sur les frontières musicales ; accepter un résiduel comme texture |
| le modèle ignore la structure du fluide (formes décorrélées) | haute | strength plus bas, contrôle flow + depth combinés, densité de fluide plus contrastée ; c'est l'objet du jalon M2 |
| l'app dilue l'effort avant que le cœur soit prouvé | moyenne | ordre des jalons strict : M2 (preuve esthétique) avant M3 (app) ; l'UI ne se construit que sur un pipeline validé |
| coût GPU des itérations esthétiques | moyenne | l'itération sur extrait de 10 s est le geste central de l'UI, grilles de comparaison en un seul run |
| obsolescence rapide des modèles vid2vid | moyenne | interface E3/E4 gelée : E4 est un module remplaçable, le reste du pipeline ne bouge pas |
| segmentation automatique des sections peu fiable | basse | sections éditables à la souris dans le Studio, ce sont des données, pas du code |
| droits musicaux si publication | basse | morceaux libres, productions d'amis, ou usage privé/démo |

---

## 09 · Questions ouvertes

- **Format cible v1** : carré 1:1 (Instagram, cohérent avec @onfaitpleindetrucs) ou 16:9 (projecteur du salon) ? Le carré simplifie E4.
- **Premier morceau** : quelque chose d'électronique avec des drops nets rend M2 plus facile à juger qu'une nappe ambient.
- **Le flicker résiduel** : à combattre systématiquement, ou à doser comme une texture (un monde qui se rêve plus vite qu'il ne se fixe) ? À trancher devant les premiers rendus, pas avant.
- **2D vs 3D** : la v1 est en fluide 2D ; une v2 pourrait simuler en 3D fine (smoke sim) pour une pseudo-depth plus riche.
- **Provisioning GPU depuis l'UI** : la v1 demande une clé API (Vast/RunPod) dans les Réglages et provisionne automatiquement, ou assume-t-on un endpoint ComfyUI déjà démarré ? L'automatique est plus « app complète », mais ajoute une surface d'erreurs.
- **Nom** : Kaika est une proposition, pas une décision.

---

*kaika 開花 · spec v0.2 · du son, un fluide ; du fluide, une fleur*
