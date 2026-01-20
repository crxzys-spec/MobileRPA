class AppError(RuntimeError):
    pass


AdbError = AppError

__all__ = ["AppError", "AdbError"]
