"""The background tasks of the platform (core.jobs) and the periodic ones the worker queues itself: (task, every).
A task takes ids, never objects, re-reads what it works on and can run twice without harm."""

PERIODIC = []
