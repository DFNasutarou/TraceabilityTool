"""アプリケーション共通の例外。"""


class AppError(Exception):
    """利用者に表示するエラー。message は日本語で書く。"""

    def __init__(self, message: str, code: str = "bad_request", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class NotFound(AppError):
    def __init__(self, message: str = "対象が見つかりません"):
        super().__init__(message, code="not_found", status=404)
