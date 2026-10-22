"""Bounded passive observations between existing input actions.

Snapshots can perturb timing and do not prove which node received an event.
They never select, focus, type, navigate, classify access or grant a retry.
"""
import json
import math
import time

PHASES=('before_pacing','after_pacing','after_select_all','after_typing','after_settle')
_JS=r'''(el,args)=>{
  const clip=value=>{
    let text='',count=0;
    for(const ch of value||''){
      if(++count>200)break;
      const n=ch.charCodeAt(0);
      text+=ch.length===1&&n>=0xD800&&n<=0xDFFF?'\uFFFD':ch;
    }
    return {text,truncated:count>200};
  };
  const value=clip(el.value),rect=el.getBoundingClientRect();
  return {same_node:el===args.original,original_connected:args.original.isConnected,
    connected:el.isConnected,visible:rect.width>0&&rect.height>0,
    focused:document.activeElement===el,read_only:el.readOnly,disabled:el.disabled,
    value:value.text,value_truncated:value.truncated,matches_query:el.value===args.query,
    selection_start:el.selectionStart,selection_end:el.selectionEnd,selection_direction:el.selectionDirection};
}'''
_BOOLS=('same_node','original_connected','connected','visible','focused','read_only',
        'disabled','value_truncated','matches_query')


def _validated(value):
    keys={*_BOOLS,'value','selection_start','selection_end','selection_direction'}
    if not isinstance(value,dict) or set(value)!=keys:raise ValueError('invalid_input_observation')
    if any(type(value[key]) is not bool for key in _BOOLS):raise ValueError('invalid_input_observation')
    text=value['value']
    if (not isinstance(text,str) or len(text)>200
            or any(0xD800<=ord(ch)<=0xDFFF for ch in text)):raise ValueError('invalid_input_observation')
    for key in ('selection_start','selection_end'):
        n=value[key]
        if n is not None and (type(n) is not int or not 0<=n<=2147483647):raise ValueError('invalid_input_observation')
    if value['selection_direction'] not in (None,'forward','backward','none'):raise ValueError('invalid_input_observation')
    return value


class InputObservation:
    def __init__(self,field,query,audit):
        self.field=field;self.query=query;self.original=None;self.original_phase=None;self.started=time.monotonic()
        self.record={'scope':'Passive input snapshots only; no access verdict or retry grant.',
                     'snapshots':[]}
        audit['input_observations']=self.record

    def capture(self,phase):
        if phase not in PHASES or len(self.record['snapshots'])>=5:return
        row={'phase':phase}
        try:
            if self.original is None:
                self.original=self.field.element_handle(timeout=250)
                if self.original is None:raise ValueError('input_unavailable')
                self.original_phase=phase
            facts=_validated(self.field.evaluate(_JS,{'original':self.original,'query':self.query},timeout=250))
            elapsed=time.monotonic()-self.started
            if not math.isfinite(elapsed) or elapsed<0:raise ValueError('invalid_clock')
            row.update(status='observed',original_phase=self.original_phase,elapsed_seconds=round(elapsed,3),**facts)
            candidate={**self.record,'snapshots':[*self.record['snapshots'],row]}
            if len(json.dumps(candidate,ensure_ascii=False,allow_nan=False).encode('utf8'))>8192:
                raise ValueError('input_observation_budget')
        except Exception as exc:
            # Diagnostic failures do not become platform/parser failures, and
            # never swallow errors from the actual input actions outside here.
            row={'phase':phase,'status':'unavailable','error_type':type(exc).__name__[:80]}
        self.record['snapshots'].append(row)

    def close(self):
        if self.original is not None:
            try:self.original.dispose()
            except Exception:pass
