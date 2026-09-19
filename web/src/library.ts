import lockSource from '../../cad/casting_box.py?raw';
import floorSource from '../../cad/captured_base.py?raw';

type Parameter = {key: string; label: string; value: number; note: string};
type Entry = {id: string; name: string; category: string; description: string; source: string; path: string; parameters: Parameter[]; instructions: string[]; validation: string};
const entries: Entry[] = [
  {id: 'slide-lock', name: 'Slide-lock joint', category: 'Fasteners · Printed assembly',
    description: 'A capped sliding clip and two matching triangular rails. Reuse the mating joint, not an isolated clip with unrelated dimensions.',
    path: 'cad/casting_box.py', source: lockSource,
    parameters: [
      {key:'lock_length',label:'Clip length',value:100,note:'mm; excludes the 3 mm cap in the reference configuration.'},
      {key:'lock_wall',label:'Clip wall / cap',value:3,note:'mm; surrounding host geometry must also be checked.'},
      {key:'lock_clearance',label:'Sliding clearance',value:0.15,note:'mm, normal to mating faces—not a horizontal or vertical gap.'},
      {key:'rail_depth',label:'Rail depth',value:8,note:'mm; coupled to the matching clip.'},
      {key:'rail_half_width',label:'Rail half-width',value:8,note:'mm; coupled to the matching clip.'},
      {key:'rail_bottom_chamfer',label:'Rail underside ramp',value:3,note:'mm; requires a supported host attachment.'}],
    instructions: ['Integrate both rails into supported mating walls; maintain their alignment and the clip removal envelope.',
      'Print a short fit coupon first. Deburr sliding faces; do not confuse clearance surfaces with the zero-gap loaded end stop.',
      'Bring the wall halves together, then slide the clip onto the rails until its cap meets the stop. Slide it off before separating the walls.',
      'Use the reference casting-box print orientations. Different dimensions or host parts require fresh support, clearance and interference checks.'],
    validation: 'The existing casting assembly has computational sliding-clearance, stop-contact, separation-retention and exported-mesh checks. A generic reusable generator has not been released. Strength, fatigue and printer fit are not physically verified.'},
  {id:'captured-floor',name:'Captured-floor joint',category:'Mating joints · Printed assembly',
    description:'A floor flange captured between a loaded horizontal seat and an upper retaining shoulder. Separate from the slide-lock clip.',
    path:'cad/captured_base.py',source:floorSource,
    parameters:[
      {key:'capture_shoulder',label:'Retaining shoulder',value:2,note:'mm radial overlap in the reference design.'},
      {key:'capture_normal_clearance',label:'Mating clearance',value:0.15,note:'mm normal to bevels; the flat shoulder uses 0.15 mm vertical clearance.'}],
    instructions:['Bring the wall halves around the flange. Seat the floor fully on the lower horizontal ledge before fitting the slide locks.',
      'Keep the loaded seat clean and flat. It has zero nominal gap; the upper shoulder prevents lift.',
      'The reference channel has a 2.062 mm roof overhang. Test printability and add removable supports if required.',
      'Dry-fit and water-test before plaster. Printed seams are not guaranteed watertight; the locating gap may leave thin plaster flash.',
      'After setting, remove the slide locks, withdraw the wall halves sideways, then release the casting from the master.'],
    validation:'The reference assembly checks downward support, upward capture and sideways withdrawal. Leak-tightness, practical strength and release are unverified. The outer plaster-bottom chamfer/flash issue remains unresolved.'}
];
function node<K extends keyof HTMLElementTagNameMap>(tag:K,text?:string,className?:string) {
  const element=document.createElement(tag);
  if(text!==undefined)element.textContent=text;
  if(className)element.className=className;
  return element;
}
let dialog:HTMLDialogElement|undefined;
export function openLibrary() {
  if(dialog){dialog.showModal();return;}
  dialog=node('dialog');dialog.id='component-library';dialog.setAttribute('aria-labelledby','library-title');
  dialog.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();dialog!.close();}});
  const heading=node('div',undefined,'library-heading');
  const title=node('h2','Components');title.id='library-title';
  const close=node('button','Close');close.setAttribute('aria-label','Close component library');close.onclick=()=>dialog!.close();
  heading.append(title,node('span','Workspace library · Reference catalog'),close);
  const layout=node('div',undefined,'library-layout');
  const catalog=node('div',undefined,'library-catalog');
  const search=node('input');search.type='search';search.placeholder='Search components…';search.setAttribute('aria-label','Search components');
  const list=node('div',undefined,'component-list');
  catalog.append(search,list,node('p','Reference entries are not yet installable components. Existing designs remain unchanged.','hint'));
  const detail=node('div',undefined,'component-detail');layout.append(catalog,detail);dialog.append(heading,layout);document.body.append(dialog);
  let selected=entries[0];
  function renderList() {
    list.replaceChildren();
    const matches=entries.filter(e=>(e.name+' '+e.category+' '+e.description).toLowerCase().includes(search.value.toLowerCase()));
    for(const entry of matches){
      const button=node('button');button.className='component-card';button.setAttribute('aria-pressed',String(entry===selected));
      button.append(node('strong',entry.name),node('small',entry.category),node('span','Reference · not released','reference-badge'));
      button.onclick=()=>{selected=entry;renderList();renderDetail();};list.append(button);
    }
    if(!matches.length)list.append(node('p','No matching components.'));
  }
  function renderDetail() {
    detail.replaceChildren();
    const entry=selected;
    detail.append(node('p',entry.category,'eyebrow'),node('h3',entry.name),node('p',entry.description),node('p','Source snapshot from this application build. No released component version or automatic insertion yet.','reference-note'));
    const tabs=node('div',undefined,'component-tabs');tabs.setAttribute('aria-label','Component information');
    const panel=node('div',undefined,'component-panel');detail.append(tabs,panel);
    const values=new Map(entry.parameters.map(p=>[p.key,p.value]));
    function show(tab:string) {
      for(const button of Array.from(tabs.querySelectorAll('button')))button.setAttribute('aria-pressed',String(button.textContent===tab));
      panel.replaceChildren();
      if(tab==='Parameters') {
        panel.append(node('p','Draft configuration only. Units: mm. The CAD engine must validate ranges and coupled fit constraints before use.','hint'));
        for(const parameter of entry.parameters){
          const label=node('label',undefined,'component-parameter');
          const input=node('input');input.type='number';input.step='any';input.min='0.001';input.max='1000';input.required=true;input.value=String(values.get(parameter.key));
          input.setAttribute('aria-label',parameter.label);
          input.oninput=()=>{
            values.set(parameter.key,input.valueAsNumber);
            draft.hidden=true;use.hidden=true;status.textContent='Draft values changed. Prepare the request again.';
          };
          label.append(node('strong',parameter.label),input,node('small',parameter.note));panel.append(label);
        }
      } else if(tab==='Instructions') {
        const steps=node('ol');steps.className='component-steps';for(const text of entry.instructions)steps.append(node('li',text));panel.append(steps);
      } else if(tab==='Source') {
        panel.append(node('p',entry.path+' · existing application implementation, not a standalone component package.','hint'));
        const pre=node('pre');pre.append(node('code',entry.source));panel.append(pre);
      } else {
        panel.append(node('h4','Validation & limitations'),node('p',entry.validation),node('h4','Reference configuration'));
        const dl=node('dl');for(const p of entry.parameters)dl.append(node('dt',p.label),node('dd',`${p.value} mm`));panel.append(dl);
        panel.append(node('p','These values describe the approved locking-base assembly. They are not a physical strength rating or a guarantee for a different host design.','hint'));
      }
    }
    for(const tab of ['Overview','Parameters','Instructions','Source']){const button=node('button',tab);button.onclick=()=>show(tab);tabs.append(button);}
    show('Overview');
    const actions=node('div',undefined,'component-actions');
    const prepare=node('button','Prepare pi request');
    const status=node('p','Creates a draft only; does not run tools, build or publish.','hint');status.setAttribute('role','status');
    const draft=node('textarea');draft.hidden=true;draft.readOnly=true;draft.rows=7;draft.setAttribute('aria-label','Component request draft');
    const use=node('button','Use draft in chat');use.hidden=true;
    prepare.onclick=()=>{
      const invalid=[...values.values()].some(value=>!Number.isFinite(value)||value<=0||value>1000);
      if(invalid){status.textContent='Enter finite draft dimensions greater than 0 and no more than 1000 mm. Engine fit constraints still apply.';draft.hidden=true;use.hidden=true;return;}
      draft.value=`Inspect the current design before making changes. I want to reuse the ${entry.name} reference (${entry.path}) with these draft parameters in mm:\n${JSON.stringify(Object.fromEntries(values),null,2)}\nReference instructions:\n${entry.instructions.join('\n')}\nValidation notes: ${entry.validation}\nCheck the mating geometry, placement and clearance constraints. This is not yet an installed reusable component. Clarify missing placement or host requirements, then prepare a validated candidate. Do not publish without my confirmation.`;
      draft.hidden=false;use.hidden=false;use.disabled=document.getElementById('chat-panel')!.hidden;
      status.textContent=use.disabled?'Draft ready. Copy it into your pi session; web chat is not connected here.':'Draft ready. Move it into chat, review it, then send explicitly.';
    };
    use.onclick=()=>{
      const input=document.getElementById('chat-input') as HTMLTextAreaElement;
      if(input.value.trim() && !window.confirm('Replace your unsent chat draft?'))return;
      input.value=draft.value;dialog!.close();input.focus();
    };
    actions.append(prepare,use,status,draft);detail.append(actions);
  }
  search.oninput=renderList;renderList();renderDetail();dialog.showModal();
}
