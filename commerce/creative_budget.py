"""One monotonic budget for optional OCR across all frames of an analysis job."""
import math
import time


class OCRBudget:
    def __init__(self,total_seconds=20,call_seconds=8,clock=time.monotonic):
        if not 0<call_seconds<=total_seconds:raise ValueError('creative_invalid_ocr_budget')
        self.total_seconds=total_seconds;self.call_seconds=call_seconds
        self.clock=clock;self.deadline=None

    def read(self,run,argv):
        # Start before invoking the runner: tool resolution, environment setup and
        # process startup also consume the budget seen by all subsequent frames.
        now=self.clock()
        if self.deadline is None:self.deadline=now+self.total_seconds
        remaining=self.deadline-now
        if remaining<=0:return {'status':'skipped','reason':'ocr_budget_exhausted'}
        try:done=run(argv,min(self.call_seconds,remaining))
        except (ValueError,TypeError) as error:
            return {'status':'unavailable','reason':'ocr_timeout' if str(error)=='creative_processing_timeout' else 'ocr_processing_failed'}
        try:
            values=[]
            for line in done.stdout.decode(errors='replace').splitlines():
                parts=line.split('\t',5)
                if len(parts)!=6:raise ValueError('invalid_ocr_line')
                confidence=float(parts[4]);bounds=[float(x) for x in parts[:4]]
                if not all(math.isfinite(x) for x in [confidence,*bounds]) or not 0<=confidence<=1:raise ValueError('invalid_ocr_values')
                values.append(dict(text=parts[5][:1000],confidence=confidence,bounds=bounds))
            return {'status':'completed','items':values}
        except (ValueError,TypeError,AttributeError):return {'status':'unavailable','reason':'ocr_invalid_output'}
