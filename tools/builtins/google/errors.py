class GoogleAuthRequiredError(RuntimeError):
    pass


class GoogleNotConnectedError(GoogleAuthRequiredError):
    pass


class GoogleOAuthNotConfiguredError(RuntimeError):
    pass


class GoogleMapsNotConfiguredError(RuntimeError):
    pass


class GmailScopeMissingError(GoogleAuthRequiredError):
    pass


class DriveScopeMissingError(GoogleAuthRequiredError):
    pass


class SheetsScopeMissingError(GoogleAuthRequiredError):
    pass


class TasksScopeMissingError(GoogleAuthRequiredError):
    pass
