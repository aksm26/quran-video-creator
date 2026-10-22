"""Run blocking work (network, rendering, ffmpeg) off the UI thread."""

from PySide6.QtCore import QObject, QRunnable, Signal


class Task(QRunnable):
    """Runs fn() in the thread pool. With progress=True, fn receives a callback progress(fraction, text)."""

    class Signals(QObject):
        done = Signal(object)
        failed = Signal(object)
        progress = Signal(float, str)

    def __init__(self, fn, progress: bool = False):
        super().__init__()
        self.fn, self.with_progress = fn, progress
        self.signals = Task.Signals()
        self.setAutoDelete(False)  # the window keeps the task (and its signals) alive until it reports back

    def run(self):
        try:
            result = self.fn(self.signals.progress.emit) if self.with_progress else self.fn()
        except Exception as e:  # reported to the UI thread, which decides how to show it
            self.signals.failed.emit(e)
        else:
            self.signals.done.emit(result)
