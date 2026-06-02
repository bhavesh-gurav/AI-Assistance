"""UI package."""

__all__ = ["JarvisApp"]


def __getattr__(name: str):  # lazy import so the package loads without customtkinter
    if name == "JarvisApp":
        from app.ui.tray_app import JarvisApp

        return JarvisApp
    raise AttributeError(name)
