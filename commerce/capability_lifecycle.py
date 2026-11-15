"""One owned media I/O worker beside the existing nonblocking extension runner."""
import threading
import time


class CapabilityLifecycle:
    def __init__(self,service):
        self.service=service;self._lock=threading.Lock();self._thread=None;self._closed=False
        self._extension_error=None;self._media_error=None;self._last_tick=None

    def status(self):
        return {'stopped':self._closed,'media_io_running':bool(self._thread and self._thread.is_alive()),
                'extension_error':self._extension_error,'media_error':self._media_error,'last_tick':self._last_tick}

    def _media_tick(self,at):
        try:
            self.service.media_providers.tick(at=at)
            execution=getattr(self.service,'media_plugin_execution',None)
            if execution:execution.tick(at=at)
            self._media_error=None
        except Exception:self._media_error='media_background_tick_failed'

    def tick(self,at=None):
        if self._closed:return
        self._last_tick=time.time() if at is None else at
        try:self.service.extensions.tick(at=at);self._extension_error=None
        except Exception:self._extension_error='extension_background_tick_failed'
        with self._lock:
            if self._closed or self._thread and self._thread.is_alive():return
            self._thread=threading.Thread(target=self._media_tick,args=(at,),name='commerce-media-io',daemon=True)
            self._thread.start()

    def recover(self):
        self.service.extensions.recover();self.service.media_providers.recover()
        execution=getattr(self.service,'media_plugin_execution',None)
        if execution:execution.recover()

    def stop(self):
        with self._lock:self._closed=True
        self.service.media_providers.stop();self.service.extensions.stop()
        execution=getattr(self.service,'media_plugin_execution',None)
        if execution:execution.stop()
        if self._thread:self._thread.join(timeout=3)
