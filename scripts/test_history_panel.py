"""Regression tests for incremental widgets, counters and polling messages."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.history_panel import HistoryPanel
from app.ops_app import AutoHubApp

class Widget:
    def __init__(self, *args, **kwargs):
        self.destroyed = False
        self.options = kwargs
    def grid(self, **kwargs): self.options.update(kwargs)
    def grid_remove(self): pass
    def grid_columnconfigure(self, *args, **kwargs): pass
    def configure(self, **kwargs): self.options.update(kwargs)
    def destroy(self): self.destroyed = True
    def winfo_exists(self): return not self.destroyed
    def winfo_rooty(self): return 10
    def winfo_height(self): return 20

def main():
    host = Mock()
    host.winfo_children.return_value = []
    host._parent_canvas.yview.return_value = (0, .2)
    host.after_idle.side_effect = lambda f: f()
    history = [{'ok': False, 'ref': str(i)} for i in range(130)]
    made=[]
    def card(*args):
        w=Widget(); made.append(w); return w
    with patch('app.history_panel.ctk.CTkFrame', Widget), patch('app.history_panel.ctk.CTkLabel', Widget), patch('app.history_panel.ctk.CTkButton', Widget), patch('app.history_panel.invoice_card', card):
        panel=HistoryPanel(host)
        panel.update([('History', history)])
        assert len(made)==50
        panel.update([('History', history)])
        assert len(made)==50, 'unchanged logs must do no rebuilding'
        panel.more('History'); panel.more('History')
        assert len(made)==130 and not any(w.destroyed for w in made)
        panel.update([('History', history+[{'ok':False,'ref':'new'}])])
        assert len(made)==131 and not any(w.destroyed for w in made), 'only one new widget'
        panel.update([('History',[])])
        assert all(w.destroyed for w in made), 'explicit clear removes widgets'
    app=SimpleNamespace(_cards=history,ok_host=Mock(),err_host=Mock(),retry_btn=Mock(),count_err=Mock(),_paint_column=Mock())
    with patch('app.ops_app.pending_cards',return_value=[{'ok':False,'ref':'pending'}]):
        AutoHubApp._paint_cards(app)
    assert app._pending_count==1
    app.retry_btn.configure.assert_called_with(text='Reenviar fallidas (1)')
    app.count_err._value.configure.assert_called_with(text='1')
    app=SimpleNamespace(_auto_on=False,cycle_label=Mock())
    AutoHubApp._set_cycle_summary(app,{'cloud_empty':1},'',1,'empty',20000)
    text=app.cycle_label.configure.call_args.kwargs['text']
    assert 'proxima' not in text and 'apagado' in text
    app._auto_on=True
    AutoHubApp._set_cycle_summary(app,{'blocked':1},'',1,'error',20000)
    text=app.cycle_label.configure.call_args.kwargs['text']
    assert 'bloqueada' in text and 'cola vacia' not in text
    source=Path('app/ops_app.py').read_text(encoding='utf-8')
    sidebar=source.split('    def _build_sidebar')[1].split('    def _build_main')[0]
    assert not any(s in sidebar for s in ['Borrar AH','Rehacer 12/13','Probar items','Prueba full'])
    print('OK: incremental 50/130/131 widgets, no redraw on unchanged logs, counters, production buttons and polling states.')
if __name__=='__main__': main()
