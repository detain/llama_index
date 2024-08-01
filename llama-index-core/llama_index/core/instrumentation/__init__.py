import inspect
from abc import ABC
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, List

from llama_index.core.instrumentation.dispatcher import (
    Dispatcher,
    Manager,
    DISPATCHER_SPAN_DECORATED_ATTR,
)
from llama_index.core.instrumentation.event_handlers import NullEventHandler
from llama_index.core.instrumentation.span_handlers import NullSpanHandler

root_dispatcher: Dispatcher = Dispatcher(
    name="root",
    event_handlers=[NullEventHandler()],
    span_handlers=[NullSpanHandler()],
    propagate=False,
)

root_manager: Manager = Manager(root_dispatcher)

# ContextVar for managing active event tags
active_event_tags = ContextVar("event_tags", default={})


@contextmanager
def event_tags(new_tags):
    token = active_event_tags.set(new_tags)
    try:
        yield
    finally:
        active_event_tags.reset(token)


def get_dispatcher(name: str = "root") -> Dispatcher:
    """Module method that should be used for creating a new Dispatcher."""
    if name in root_manager.dispatchers:
        return root_manager.dispatchers[name]

    candidate_parent_name = ".".join(name.split(".")[:-1])
    if candidate_parent_name in root_manager.dispatchers:
        parent_name = candidate_parent_name
    else:
        parent_name = "root"

    new_dispatcher = Dispatcher(
        name=name,
        root_name=root_dispatcher.name,
        parent_name=parent_name,
        manager=root_manager,
    )
    root_manager.add_dispatcher(new_dispatcher)
    return new_dispatcher


class DispatcherSpanMixin(ABC):
    """
    Apply the `dispatcher.span` decorator to implementations of abstract methods, as well
    as any methods previously decorated (in any base class) that are being overridden by
    a subclass. For example, if class `A` has abstract method `f`, and class `B` inherits
    from `A` and provides an implementation of `f`, then `B.f` will be decorated by the mixin.
    Furthermore, if `B` has a non-abstract method `g` that is decorated by `dispatcher.span`
    and new class `C` inherits from `B` and overrides `g`, then `C.g` will also be decorated
    by the mixin. Note that users can still manually apply `dispatcher.span` to the methods
    in their custom subclasses without creating duplicate spans because the `dispatcher.span`
    decorator should be idempotent.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        abstract_methods: List[str] = []
        decorated_methods: List[str] = []
        for base_cls in inspect.getmro(cls):
            if base_cls is cls:
                continue
            for attr, method in base_cls.__dict__.items():
                if not callable(method):
                    continue
                if (
                    hasattr(method, "__isabstractmethod__")
                    and method.__isabstractmethod__
                ):
                    abstract_methods.append(attr)
                elif hasattr(method, DISPATCHER_SPAN_DECORATED_ATTR):
                    decorated_methods.append(attr)
        dispatcher = get_dispatcher(cls.__module__)
        for attr, method in cls.__dict__.items():
            if (
                not callable(method)
                or hasattr(method, "__isabstractmethod__")
                and method.__isabstractmethod__
            ):
                continue
            if attr in abstract_methods or attr in decorated_methods:
                setattr(cls, attr, dispatcher.span(method))
