class IDOSError(Exception):
    pass


class ValidationError(IDOSError):
    pass


class StateTransitionError(IDOSError):
    pass


class EntityNotFoundError(IDOSError):
    pass


class EventBusError(IDOSError):
    pass
