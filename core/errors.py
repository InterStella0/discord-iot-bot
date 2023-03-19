class ViewError(Exception):
    pass


class NotAuthorError(ViewError):
    pass


class FatalViewError(ViewError):
    pass

