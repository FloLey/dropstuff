"""Phase 0: package imports and core third-party deps are available."""
import importlib


def test_version():
    import kaika
    assert kaika.__version__


def test_core_deps_importable():
    for mod in ("numpy", "scipy", "librosa", "cv2", "yaml", "imageio_ffmpeg"):
        importlib.import_module(mod)


def test_ffmpeg_binary_available():
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    assert exe and __import__("os").path.exists(exe)
