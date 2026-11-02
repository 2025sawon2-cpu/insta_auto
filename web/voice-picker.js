/* One user-confirmed Google AI Studio voice; old result labels stay historical. */
(()=>{
 const label=id=>id&&id!=='Arlo'?'이전 목소리 ('+id+')':'Arlo · Google AI Studio';
 function bind(root){
  const box=root.querySelector('[data-voice-picker]');if(!box)return;
  const field=box.querySelector('[data-field="voice-profile"]');
  const current=box.querySelector('[data-current-voice]');
  field.value='Arlo';current.textContent=label('Arlo');
  const button=box.querySelector('[data-choose-voice]');
  if(button){button.textContent='Arlo 확정';button.disabled=true;}
 }
 window.VoicePicker={bind,label};
})();
