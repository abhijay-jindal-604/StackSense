/* StackSense · Fitting Bay (f5) — the robot, its parts, the core gauge, the bay and the shop-floor effects.
   Screenprint treatment: flat base tone + one shadow tone + halftone dots + ink outline; orange layer printed slightly off register. */
(function(){
/* literal hexes (dark bay); C emits themeable CSS vars with these as fallbacks, so [data-theme=print] can re-ink the robot */
const HEX={s1:'#8F9AA6',s2:'#5F6976',s3:'#38414C',sh:'#C9D1D9',ink:'#12161C',or:'#F26A2C',or2:'#B9461A',orh:'#FFC49A',
  mu:'#F3B53A',cu:'#C07A47',cream:'#EDE6D6',face:'#F6DDB0',faceOff:'#6E6A62',faceOut:'#F3C53A'};
const VAR={faceOff:'face-off',faceOut:'face-out'};
const C=Object.fromEntries(Object.entries(HEX).map(([k,h])=>[k,`var(--bot-${VAR[k]||k},${h})`]));
const MIS='transform="translate(1.4,-1)"'; // print misregistration on the orange/mustard layer
let uid=0;

/* ---------- primitives ---------- */
const P=(d,f,extra='')=>`<path d="${d}" fill="${f}" ${extra}/>`;
const O=(d,w=3)=>`<path d="${d}" fill="none" stroke="${C.ink}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"/>`;
const L=(d,c,w)=>`<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
/* a screenprinted solid: base, shadow tone, halftone over the shadow, highlight, ink contour */
function solid(d,shade,hi,base=C.s1,w=3){
  return P(d,base)+(shade?P(shade,C.s2)+P(shade,'url(#fb-dots)'):'')+(hi?L(hi,C.sh,2.4):'')+O(d,w);
}
const circ=(x,y,r,f,w=2.5)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="${f}" stroke="${C.ink}" stroke-width="${w}"/>`;
const rivet=(x,y,r=1.9)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="${C.sh}" stroke="${C.ink}" stroke-width=".9"/>`;
function ball(x,y,r,hub=C.s3){ // shaded ball joint
  return circ(x,y,r,C.s2,0)+`<circle cx="${x-r*.14}" cy="${y-r*.14}" r="${r*.84}" fill="${C.s1}"/>`+
    `<circle cx="${x+r*.25}" cy="${y+r*.25}" r="${r*.6}" fill="url(#fb-dots)" opacity=".7"/>`+
    L(`M${x-r*.62} ${y-r*.2} A${r*.66} ${r*.66} 0 0 1 ${x-r*.2} ${y-r*.62}`,C.sh,2)+
    `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${C.ink}" stroke-width="2.6"/>`+circ(x,y,r*.38,hub,1.6);
}

/* boot soles (shared by the chassis and the cradle's clip, so the deck runs behind the boots) */
const BOOT_L='M140 566 L194 566 L198 596 Q198 604 190 604 L138 604 Q131 604 133 596 Z';
const BOOT_R='M206 566 L260 566 L267 596 Q269 604 262 604 L210 604 Q202 604 202 596 Z';
/* a 3/4-view block: front face, lit top, shaded side (light from top-left, depth d up-right) */
function box3(x,y,w,h,d=4,base=C.s1,w2=2){
  const top=`M${x} ${y} L${x+d} ${y-d} L${x+w+d} ${y-d} L${x+w} ${y} Z`,side=`M${x+w} ${y} L${x+w+d} ${y-d} L${x+w+d} ${y+h-d} L${x+w} ${y+h} Z`;
  return P(`M${x} ${y} h${w} v${h} h${-w} Z`,base)+P(top,C.sh)+P(side,C.s2)+P(side,'url(#fb-dots)')+
    O(`M${x} ${y} L${x+d} ${y-d} L${x+w+d} ${y-d} L${x+w+d} ${y+h-d} L${x+w} ${y+h} L${x} ${y+h} Z M${x} ${y} H${x+w} V${y+h} M${x+w} ${y} L${x+w+d} ${y-d}`,w2);
}
const hexbolt=(x,y,r=2.6)=>`<path d="M${x-r} ${y} L${x-r/2} ${y-r*.86} L${x+r/2} ${y-r*.86} L${x+r} ${y} L${x+r/2} ${y+r*.86} L${x-r/2} ${y+r*.86} Z" fill="${C.sh}" stroke="${C.ink}" stroke-width="1.1"/>`;

/* ---------- shared defs (inject once per page) ---------- */
function defs(){
  if(document.getElementById('fb-defs'))return;
  const d=document.createElement('div');
  d.innerHTML=`<svg id="fb-defs" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <pattern id="fb-hz" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="14" height="14" fill="${C.mu}"/><rect width="7" height="14" fill="${C.ink}"/></pattern>
  <pattern id="fb-hz-o" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="14" height="14" fill="${C.or}"/><rect width="7" height="14" fill="${C.ink}"/></pattern>
  <pattern id="fb-dots" width="4.2" height="4.2" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="2.1" cy="2.1" r=".95" fill="${C.ink}" opacity=".55"/></pattern>
  <pattern id="fb-dots-l" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="3.5" cy="3.5" r="1.25" fill="#fff" opacity=".5"/></pattern>
  <pattern id="fb-dots-big" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(30)"><circle cx="4.5" cy="4.5" r="1.7" fill="${C.ink}" opacity=".35"/></pattern>
  <linearGradient id="fb-cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--cone)" stop-opacity=".26"/><stop offset=".7" stop-color="var(--cone)" stop-opacity=".08"/><stop offset="1" stop-color="var(--cone)" stop-opacity=".02"/></linearGradient>
  <radialGradient id="fb-pool" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="var(--cone)" stop-opacity=".22"/><stop offset="1" stop-color="var(--cone)" stop-opacity="0"/></radialGradient>
  <clipPath id="fb-noboots"><path clip-rule="evenodd" d="M60 560 H340 V680 H60 Z ${BOOT_L} ${BOOT_R}"/></clipPath>
  </defs></svg>`;
  document.body.prepend(d.firstElementChild);
}

/* ---------- parts ---------- */
const PART={};
/* VISOR = frontend: the helmet with its orange visor slot */
PART.visor=()=>{
  const shell='M156 150 L153 106 C153 79 174 63 200 63 C226 63 247 79 247 106 L244 150 Z';
  return solid(shell,'M216 65 C234 71 247 86 247 106 L244 150 L227 150 C231 120 229 88 216 65 Z','M165 128 L164 104 C164 88 172 76 186 70')+
   P('M195 63 L205 63 L204 91 L196 91 Z',C.s2)+O('M195 63 L205 63 L204 91 L196 91 Z',1.6)+
   `<rect x="159" y="93" width="82" height="29" rx="7" fill="${C.ink}"/>`+
   `<g ${MIS}><rect x="164" y="97" width="72" height="20" rx="5" fill="${C.or}"/><rect x="164" y="108" width="72" height="9" rx="4" fill="${C.or2}"/></g>`+
   `<g class="eyes"><ellipse cx="184" cy="106" rx="8" ry="3.4" fill="${C.orh}"/><ellipse cx="216" cy="106" rx="8" ry="3.4" fill="${C.orh}"/></g>`+
   L('M170 101 L190 101',C.orh,2)+`<rect x="164" y="97" width="72" height="20" rx="5" fill="none" stroke="${C.ink}" stroke-width="1.6"/>`+
   ball(154,114,12)+ball(246,114,12)+
   [188,196,204,212].map(x=>`<rect x="${x-2}" y="127" width="4" height="15" rx="2" fill="${C.ink}"/>`).join('')+
   L('M159 146 L241 146',C.ink,2)+rivet(166,86)+rivet(234,86)+rivet(164,138)+rivet(236,138);
};
PART.visor.ghost='M156 150 L153 106 C153 79 174 63 200 63 C226 63 247 79 247 106 L244 150 Z M176 150 L176 100 L224 100 L224 150 M176 122 L224 122';
PART.visor.hit='M146 156 L143 104 C143 72 170 54 200 54 C230 54 257 72 257 104 L254 156 Z';
PART.visor.at=[200,108]; PART.visor.box='138 50 124 112';

/* SPINE = backend: segmented coils on a rod between ribcage and pelvis */
PART.spine=()=>{
  let s=`<rect x="193" y="278" width="14" height="74" fill="${C.s3}" stroke="${C.ink}" stroke-width="2"/>`;
  for(let i=0;i<7;i++){const y=283+i*9.4,w=i%2?38:44,x=200-w/2;
    s+=`<rect x="${x}" y="${y}" width="${w}" height="7.2" rx="3.6" fill="${C.s1}"/><rect x="${x+w*.62}" y="${y}" width="${w*.38}" height="7.2" rx="3.6" fill="${C.s2}"/>`+
      `<rect x="${x+w*.62}" y="${y}" width="${w*.38}" height="7.2" rx="3.6" fill="url(#fb-dots)"/>`+L(`M${x+5} ${y+2.2} L${x+w*.45} ${y+2.2}`,C.sh,1.4)+
      `<rect x="${x}" y="${y}" width="${w}" height="7.2" rx="3.6" fill="none" stroke="${C.ink}" stroke-width="1.8"/>`;}
  return s;
};
PART.spine.ghost='M193 278 h14 v74 h-14 Z';
PART.spine.hit='M168 274 h64 v82 h-64 Z';
PART.spine.at=[200,316]; PART.spine.box='160 268 80 92';

/* CRADLE = hosting: the hazard-faced platform the body stands in */
/* ref_cradle_boltons "robot standing platform": a riveted steel base plate seen from slightly above,
   a hazard-striped deck on it, and four foot clamps gripping the boot soles. The deck runs behind the boots (clipped). */
function clamp(x,m){ // U-bracket jaw straddling a boot edge; m=1 opens right, -1 opens left
  const pad=`M${x-9} 604 L${x+9} 604 L${x+11} 610 L${x-7} 610 Z`;
  const jaw=`M${x-5} 592 L${x-2} 589 L${x+8} 589 L${x+5} 592 Z`;
  return P(pad,C.s2)+O(pad,1.6)+
    `<g ${MIS}><rect x="${x-5}" y="592" width="10" height="13" fill="${C.or}"/></g>`+
    P(jaw,C.sh)+P(`M${x+5} 592 L${x+8} 589 L${x+8} 602 L${x+5} 605 Z`,C.or2)+
    O(`M${x-5} 592 L${x-2} 589 L${x+8} 589 L${x+8} 602 L${x+5} 605 L${x-5} 605 Z M${x-5} 592 H${x+5} V605`,1.8)+
    L(`M${x-1*m} 593 V600`,C.ink,2.2)+circ(x+2*m,601,1.8,C.s3,1);
}
PART.cradle=()=>{
  const plate='M98 598 L302 598 L322 636 L78 636 Z', plateFront='M78 636 L322 636 L322 646 L78 646 Z';
  const deck='M112 591 L288 591 L305 624 L95 624 Z', deckFront='M95 624 L305 624 L305 630 L95 630 Z';
  return `<g clip-path="url(#fb-noboots)">`+
    /* feet under the plate */
    `<rect x="98" y="645" width="26" height="10" fill="${C.s3}" stroke="${C.ink}" stroke-width="2"/><rect x="276" y="645" width="26" height="10" fill="${C.s3}" stroke="${C.ink}" stroke-width="2"/>`+
    /* steel base plate: lit top rim, shaded front edge with halftone */
    P(plate,C.s1)+P('M250 598 L302 598 L322 636 L262 636 Z',C.s2)+P('M250 598 L302 598 L322 636 L262 636 Z','url(#fb-dots)')+
    P(plateFront,C.s2)+P(plateFront,'url(#fb-dots)')+L('M86 633 L120 633',C.sh,1.8)+O(plate,2.6)+O(plateFront,2.6)+
    [102,126,150,174,226,250,274,298].map(x=>rivet(x,641,1.5)).join('')+
    /* hazard deck with its front thickness */
    P(deck,'url(#fb-hz)')+P('M246 591 L288 591 L305 624 L258 624 Z','url(#fb-dots-big)')+O(deck,2.4)+
    P(deckFront,C.ink)+L('M100 627 L300 627',C.s3,1.4)+
    /* corner hex bolts on the plate rim */
    hexbolt(104,602)+hexbolt(296,602)+hexbolt(88,632)+hexbolt(312,632)+
    /* nameplate with two status lights on the front edge */
    `<rect x="176" y="637" width="48" height="8" fill="${C.ink}"/>`+
    `<g ${MIS}><rect x="181" y="639" width="6" height="4" fill="${C.or}"/><rect x="190" y="639" width="6" height="4" fill="${C.or}"/></g>`+L('M201 641 L219 641',C.s2,1.6)+
    `</g>`+
    clamp(131,1)+clamp(192,-1)+clamp(208,1)+clamp(268,-1);
};
PART.cradle.ghost='M98 598 L302 598 L322 636 L322 646 L78 646 L78 636 Z';
PART.cradle.hit='M70 584 h260 v76 h-260 Z';
PART.cradle.at=[200,618]; PART.cradle.box='70 582 260 78';

/* CORE = database: a pressure gauge whose band is the cost estimate and whose needle is your budget */
function gaugeScale(g){
  const top=Math.max(g.high||0,g.budget||0)*1.15||100, step=top>500?100:top>150?50:10;
  return Math.ceil(top/step)*step;
}
const ang=(v,max)=>-120+240*Math.min(Math.max(v/max,0),1);
const pt=(a,r)=>[r*Math.sin(a*Math.PI/180),-r*Math.cos(a*Math.PI/180)];
function arc(a1,a2,r){const[p,q]=pt(a1,r),[u,v]=pt(a2,r);return `M${p.toFixed(2)} ${q.toFixed(2)} A${r} ${r} 0 ${a2-a1>180?1:0} 1 ${u.toFixed(2)} ${v.toFixed(2)}`;}
function ring(){let s='';for(let i=0;i<24;i+=2){const a1=i*15,a2=a1+15,[p,q]=pt(a1,29.2),[u,v]=pt(a2,29.2),[w,x]=pt(a2+7,24.6),[y,z]=pt(a1+7,24.6);
  s+=`<path d="M${p.toFixed(2)} ${q.toFixed(2)} A29.2 29.2 0 0 1 ${u.toFixed(2)} ${v.toFixed(2)} L${w.toFixed(2)} ${x.toFixed(2)} A24.6 24.6 0 0 0 ${y.toFixed(2)} ${z.toFixed(2)} Z" fill="${C.or}"/>`;}
  return `<g ${MIS}>${s}</g>`;}
function gauge(g={},o={}){
  const R=30,max=gaugeScale(g),inBand=g.budget>=g.low&&g.budget<=g.high,lit=o.lit!==false;
  const aL=ang(g.low||0,max),aH=ang(g.high||0,max),aB=ang(g.budget||0,max);
  const ticks=[...Array(9)].map((_,i)=>{const a=-120+i*30,[x1,y1]=pt(a,18.2),[x2,y2]=pt(a,21);return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${C.ink}" stroke-width="1.3"/>`;}).join('');
  const [bx1,by1]=pt(aB,11),[bx2,by2]=pt(aB,22.5);
  const face=inBand?C.face:C.faceOut;
  return `<g class="gauge ${inBand?'in':'out'}" data-budget-angle="${aB}">
   <circle r="${R}" fill="${C.ink}"/>${ring()}<circle r="${R}" fill="none" stroke="${C.ink}" stroke-width="2.6"/>
   ${[45,135,225,315].map(a=>{const[x,y]=pt(a,27.2);return rivet(x,y,1.6)}).join('')}
   <circle r="24" fill="${C.s3}" stroke="${C.ink}" stroke-width="2"/>
   <circle r="21.4" fill="${C.faceOff}"/>
   <circle class="face" r="21.4" fill="${face}" ${lit?'':'opacity="0"'}/>
   <path d="${arc(aL,aH,15.6)}" fill="none" stroke="${C.or}" stroke-width="5.2" ${MIS}/>
   <path d="${arc(aL,aH,15.6)}" fill="none" stroke="${C.ink}" stroke-width=".8" stroke-dasharray="1.2 2.4"/>
   ${ticks}
   <line x1="${bx1}" y1="${by1}" x2="${bx2}" y2="${by2}" stroke="${C.ink}" stroke-width="2"/>
   <g class="needle" style="--aB:${aB}deg;transform:rotate(var(--aB))"><line y1="4" y2="-17.5" stroke="${C.ink}" stroke-width="2.6" stroke-linecap="round"/><circle r="3.3" fill="${C.or}" stroke="${C.ink}" stroke-width="1.3"/></g>
   ${L('M-15 -9 A17.5 17.5 0 0 1 2 -17.4','#fff',2).replace('/>',' opacity=".45"/>')}
   <circle r="21.4" fill="none" stroke="${C.ink}" stroke-width="1.6"/>
  </g>`;
}
PART.core=(g,o)=>`<g transform="translate(200 220)">${gauge(g,o)}</g>`;
PART.core.ghost='M230 220 A30 30 0 1 1 170 220 A30 30 0 1 1 230 220 Z';
PART.core.hit='M238 220 A38 38 0 1 1 162 220 A38 38 0 1 1 238 220 Z';
PART.core.at=[200,220]; PART.core.box='164 184 72 72';

/* ---------- chassis: always present; the bare skeleton the parts bolt onto ---------- */
function chassis(){
  const torso='M132 172 Q200 158 268 172 L278 228 Q272 262 248 282 L152 282 Q128 262 122 228 Z';
  return `<g class="chassis">`+
  /* copper wiring behind the spine */
  L('M184 280 C172 300 188 324 178 352',C.ink,5.5)+L('M184 280 C172 300 188 324 178 352',C.cu,3)+
  L('M216 280 C228 300 212 324 222 352',C.ink,5.5)+L('M216 280 C228 300 212 324 222 352',C.cu,3)+
  /* legs */
  solid('M158 404 L190 404 L186 470 L156 470 Z','M178 404 L190 404 L186 470 L175 470 Z','M162 410 L160 462')+
  solid('M210 404 L242 404 L244 470 L214 470 Z','M232 404 L242 404 L244 470 L233 470 Z','M215 410 L217 462')+
  solid('M152 488 L190 488 L186 566 L154 566 Z','M176 488 L190 488 L186 566 L173 566 Z','M157 496 L158 558')+L('M154 530 L188 530',C.ink,1.6)+
  solid('M210 488 L248 488 L246 566 L214 566 Z','M234 488 L248 488 L246 566 L234 566 Z','M215 496 L217 558')+L('M212 530 L247 530',C.ink,1.6)+
  `<g ${MIS}><circle cx="171" cy="478" r="14" fill="${C.mu}"/><circle cx="229" cy="478" r="14" fill="${C.mu}"/></g>`+
  `<circle cx="171" cy="478" r="14" fill="none" stroke="${C.ink}" stroke-width="2.6"/><circle cx="229" cy="478" r="14" fill="none" stroke="${C.ink}" stroke-width="2.6"/>`+
  circ(171,478,5.5,C.s3,1.6)+circ(229,478,5.5,C.s3,1.6)+
  solid('M140 566 L194 566 L198 596 Q198 604 190 604 L138 604 Q131 604 133 596 Z','M176 566 L194 566 L198 596 Q198 604 190 604 L178 604 Z','M137 588 Q150 580 164 586')+L('M134 598 L197 598',C.ink,2)+
  solid('M206 566 L260 566 L267 596 Q269 604 262 604 L210 604 Q202 604 202 596 Z','M242 566 L260 566 L267 596 Q269 604 262 604 L246 604 Z','M207 588 Q220 580 234 586')+L('M203 598 L267 598',C.ink,2)+
  /* pelvis */
  solid('M148 350 L252 350 L264 368 L238 394 L162 394 L136 368 Z','M226 350 L252 350 L264 368 L238 394 L222 394 Q236 372 226 350 Z','M142 366 L154 354')+
  `<rect x="186" y="359" width="28" height="16" rx="2" fill="${C.s2}" stroke="${C.ink}" stroke-width="1.6"/>`+rivet(192,367)+rivet(208,367)+
  ball(174,399,11)+ball(226,399,11)+
  /* arms (left, then right; shade always on the +x side, light from top-left) */
  solid('M103 204 L137 208 L126 287 L93 283 Z','M125 206 L137 208 L126 287 L114 286 Z','M102 214 L96 272')+L('M97 262 L129 266',C.ink,1.6)+
  solid('M297 204 L263 208 L274 287 L307 283 Z','M285 205 L297 204 L307 283 L295 285 Z','M268 216 L277 276')+L('M303 262 L271 266',C.ink,1.6)+
  `<g ${MIS}><circle cx="110" cy="291" r="12" fill="${C.mu}"/><circle cx="290" cy="291" r="12" fill="${C.mu}"/></g>`+
  `<circle cx="110" cy="291" r="12" fill="none" stroke="${C.ink}" stroke-width="2.6"/><circle cx="290" cy="291" r="12" fill="none" stroke="${C.ink}" stroke-width="2.6"/>`+circ(110,291,4.5,C.s3,1.4)+circ(290,291,4.5,C.s3,1.4)+
  solid('M94 300 L127 302 L121 368 L88 366 Z','M114 301 L127 302 L121 368 L109 367 Z','M96 308 L92 358')+L('M90 354 L123 356',C.ink,1.6)+
  solid('M306 300 L273 302 L279 368 L312 366 Z','M293 301 L306 300 L312 366 L300 367 Z','M277 310 L281 358')+L('M310 354 L277 356',C.ink,1.6)+
  hand(1)+hand(-1)+
  /* neck + ribcage shell */
  `<rect x="188" y="146" width="24" height="22" fill="${C.s3}" stroke="${C.ink}" stroke-width="2"/>`+L('M190 153 L210 153 M190 160 L210 160',C.ink,1.4)+
  solid(torso,'M236 166 Q256 168 268 172 L278 228 Q272 262 248 282 L226 282 Q246 246 238 196 Z','M141 190 Q137 214 142 240')+
  solid('M168 164 Q200 156 232 164 L230 175 Q200 168 170 175 Z',null,null,C.s2,1.8)+
  L('M140 254 Q200 268 260 254',C.ink,1.5)+
  [148,166,184,216,234,252].map((x,i)=>rivet(x,i<3?184-i*2.6:184-(5-i)*2.6)).join('')+
  [150,170,230,250].map(x=>rivet(x,258+(x<200?(x-140)*.12:(260-x)*.12))).join('')+
  `<rect x="143" y="196" width="28" height="9" fill="url(#fb-hz)" stroke="${C.ink}" stroke-width="1.3"/>`+
  `<rect x="232" y="192" width="24" height="13" fill="${C.cream}" stroke="${C.ink}" stroke-width="1.3"/>`+L('M236 197 L251 197 M236 201 L246 201',C.ink,1.3)+
  /* core socket with exposed wiring */
  `<circle cx="200" cy="220" r="33" fill="${C.ink}"/>`+
  L('M178 232 C190 212 206 238 222 212',C.cu,2.6)+L('M182 205 C196 226 210 198 221 230',C.s2,2.6)+L('M190 240 C196 228 204 246 212 236',C.cu,2)+
  ball(122,186,24)+ball(278,186,24)+pauldron(1)+pauldron(-1)+
  `</g>`;
}
function pauldron(m){
  const X=x=>m===1?x:400-x,M=a=>a.replace(/(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)/g,(_,x,y)=>X(+x)+' '+y);
  const d=M('M92 200 C88 168 106 156 126 156 C142 156 151 164 154 176 L141 181 C134 173 117 172 108 183 L103 202 Z');
  const sh=m===1?M('M126 156 C142 156 151 164 154 176 L141 181 C136 175 130 172 124 172 Z'):M('M92 200 C88 168 106 156 126 156 C116 160 106 172 103 202 Z');
  return solid(d,sh,M('M97 190 C97 172 108 163 122 161'))+rivet(X(100),192)+rivet(X(112),166)+rivet(X(140),164);
}
function hand(m){ // m=1 left, -1 right
  const X=x=>m===1?x:400-x;
  const palm=`M${X(90)} 374 L${X(120)} 376 L${X(118)} 394 L${X(92)} 392 Z`;
  const f=[[94,392,92,413],[101,393,100,417],[108,394,108,416],[115,394,117,410],[119,380,128,394]].map(([a,b,c,d])=>`M${X(a)} ${b} L${X(c)} ${d}`).join(' ');
  return L(f,C.ink,8)+L(f,C.s1,4.4)+solid(palm,`M${X(m===1?110:100)} 375 L${X(m===1?120:90)} 376 L${X(m===1?118:92)} 394 L${X(m===1?108:102)} 393 Z`,null)+
    circ(X(105),371,6,C.s3,1.8);
}

/* ---------- bolt-ons = supporting services ---------- */
const GLYPH={
  auth:'M-4 -1 V-4 A4 4 0 0 1 4 -4 V-1 M-6.5 -1 H6.5 V7 H-6.5 Z M0 2 V4.5',
  realtime:'M0 7 V-1 M-5 -7 A7 7 0 0 0 -5 1 M5 -7 A7 7 0 0 1 5 1 M-2.6 -4.6 A3.5 3.5 0 0 0 -2.6 -.4 M2.6 -4.6 A3.5 3.5 0 0 1 2.6 -.4',
  payments:'M-7.5 -5 H7.5 V5 H-7.5 Z M-7.5 -1.5 H7.5 M-4.5 2.4 H-1',
  storage:'M-6.5 -5.5 H6.5 V5.5 H-6.5 Z M-6.5 -1.5 H6.5 M-2 -5.5 V-1.5 M2 -5.5 V-1.5',
  cdn:'M0 -6.5 A6.5 6.5 0 1 1 0 6.5 A6.5 6.5 0 1 1 0 -6.5 Z M0 -6.5 C-3.6 -3 -3.6 3 0 6.5 C3.6 3 3.6 -3 0 -6.5 M-6.5 0 H6.5',
  queue:'M-7 -5 H2 M-7 0 H2 M-7 5 H2 M5.5 -5 V5 M3 2.6 L5.5 5.2 L8 2.6',
  sms:'M-7.5 -6 H7.5 V3 H-1 L-5 6.5 V3 H-7.5 Z M-4 -1.5 H4',
  push:'M-5 3 V-1 A5 5 0 0 1 5 -1 V3 L6.6 5 H-6.6 Z M-1.6 6.6 A1.6 1.6 0 0 0 1.6 6.6 M0 -6 V-7.2',
  search:'M-1.5 -1.5 m-5 0 a5 5 0 1 0 10 0 a5 5 0 1 0 -10 0 M2 2 L6.5 6.5',
  observability:'M-7.5 1 H-4 L-2 -5 L1.2 6 L3.2 -1 H7.5',
  ci_cd:'M0 -6.5 A6.5 6.5 0 1 1 -6.2 2 M-6.2 2 L-7.5 -2 M-6.2 2 L-2.4 .8 M0 -2.4 A2.4 2.4 0 1 1 0 2.4 A2.4 2.4 0 1 1 0 -2.4',
  email:'M-7.5 -5.5 H7.5 V5.5 H-7.5 Z M-7.5 -5.5 L0 1 L7.5 -5.5',
  cache:'M-6 -5 H6 V5 H-6 Z M-3 -2 L1 0 L-3 2 M2 3 H4',
  ml:'M-5 -5 h10 v10 h-10 Z M-2 -2 h4 v4 h-4 Z M-5 -1 h-2 M5 -1 h2 M-1 -5 v-2 M-1 5 v2',
  other:'M0 -6.5 L5.6 -3.25 L5.6 3.25 L0 6.5 L-5.6 3.25 L-5.6 -3.25 Z M0 -2.2 A2.2 2.2 0 1 1 0 2.2 A2.2 2.2 0 1 1 0 -2.2'
};
const SLOT={auth:[118,160],realtime:[282,160],payments:[159,372],storage:[241,372],cdn:[109,330],queue:[291,330],
  sms:[172,436],push:[228,436],search:[170,524],observability:[230,524],ci_cd:[150,236],email:[250,236],cache:[250,236],ml:[150,236],other:[250,236]};
const SLOT_ORDER=['auth','realtime','payments','storage','cdn','queue','sms','push','search','observability','ci_cd','email','cache','ml','other'];
/* bolt-ons after ref_cradle_boltons: small 3/4-view modules standing on a riveted mounting plate.
   Envelope: x -18..18, y -16..13 (antenna to -34). Plate top face y 4..9, front edge y 9..13. */
const MOUNT_TOP='M-17 9 L-12 4 L18 4 L13 9 Z', MOUNT_FRONT='M-17 9 H13 V13 H-17 Z', MOUNT_SIDE='M13 9 L18 4 L18 8 L13 13 Z';
const MOUNT_ALL='M-17 9 L-12 4 L18 4 L18 8 L13 13 L-17 13 Z M-17 9 H13 V13 M13 9 L18 4';
const mount=()=>P(MOUNT_TOP,C.s1)+P(MOUNT_FRONT,C.s3)+P(MOUNT_SIDE,C.s3)+P(MOUNT_SIDE,'url(#fb-dots)')+O(MOUNT_ALL,1.8)+rivet(-13,7.6,1.2)+rivet(14,5.4,1.2)+rivet(-14,11,1)+rivet(10,11,1);
const lineO=(d,c,w)=>L(d,C.ink,w+2)+L(d,c,w); // a stroked rod with an ink casing
function gearPath(cx,cy,ro,ri,n=8){let d='';for(let i=0;i<n*2;i++){const a=i*Math.PI/n,r=i%2?ri:ro,a1=a-Math.PI/n*.42,a2=a+Math.PI/n*.42;
  d+=(i?'L':'M')+(cx+r*Math.sin(a1)).toFixed(2)+' '+(cy-r*Math.cos(a1)).toFixed(2)+' L'+(cx+r*Math.sin(a2)).toFixed(2)+' '+(cy-r*Math.cos(a2)).toFixed(2)+' ';}return d+'Z';}
const OBJ={
  auth:()=>box3(-10,-12,16,18,3)+lineO('M-5 -4 V-8.5 A3.5 3.5 0 0 1 2 -8.5 V-4',C.s1,2.2)+
    `<g ${MIS}><rect x="-7.5" y="-4" width="12" height="10" fill="${C.mu}"/></g>`+P('M1.5 -4 h3 v10 h-3 Z',C.or2)+O('M-7.5 -4 h12 v10 h-12 Z',1.8)+circ(-1.5,0,1.5,C.ink,0)+L('M-1.5 0 V3.4',C.ink,1.6),
  realtime:()=>lineO('M-6 -5 L-10 -20',C.s1,1.4)+lineO('M2 -5 V-30',C.s1,1.6)+circ(2,-31,2.8,C.or,1.4)+
    L('M10 -6 l3 -2 l-6 -2.2 l6 -2.2 l-6 -2.2 l6 -2.2 l-3 -2',C.ink,3.4)+L('M10 -6 l3 -2 l-6 -2.2 l6 -2.2 l-6 -2.2 l6 -2.2 l-3 -2',C.cu,1.6)+
    box3(-11,-3,19,10,4)+`<rect x="-8.5" y="-1" width="9" height="5" fill="${C.cream}" stroke="${C.ink}" stroke-width="1.1"/>`+L('M-6.5 3 L-3 0',C.or,1.4)+circ(4,1.8,2.1,C.s3,1.1),
  storage:()=>box3(-12,-11,20,18,5)+L('M-10 -9 L6 5 M6 -9 L-10 5',C.ink,1.5)+`<g ${MIS}><rect x="-3.5" y="-11" width="3.5" height="18" fill="${C.or}"/></g>`+
    P('M-3.5 -11 L1.5 -16 L5 -16 L0 -11 Z',C.or2)+O('M-3.5 -11 h3.5 v18 h-3.5 Z',1.2),
  push:()=>box3(-2,-6,7,12,3,C.s2)+`<g ${MIS}>${P('M-12 1 C-12 -16 7 -16 7 1 Z',C.mu)}</g>`+P('M0 -13 C5 -11 7 -6 7 1 L1 1 C2 -5 2 -9 0 -13 Z',C.or)+
    L('M-9 -5 C-9 -9 -7 -11 -4 -12',C.cream,1.6)+O('M-12 1 C-12 -16 7 -16 7 1 Z',2)+`<rect x="-13.5" y="0" width="22" height="3.4" fill="${C.s3}" stroke="${C.ink}" stroke-width="1.4"/>`+
    lineO('M6 -1 L13 -13',C.s1,1.4)+circ(13.5,-14,2.6,C.s1,1.3),
  payments:()=>P('M-4 -9 L-4 -20 L6 -20 L6 -9 Z',C.cream)+L('M-4 -16.5 H6',C.ink,1.6)+O('M-4 -9 L-4 -20 L6 -20 L6 -9',1.6)+
    box3(-12,-7,20,14,4)+L('M-7 -9 L7 -9',C.ink,2)+`<g ${MIS}><rect x="-12" y="-2" width="20" height="4" fill="${C.or}"/></g>`+O('M-12 -2 h20 v4 h-20 Z',1.2)+circ(-2,5,1.3,C.ink,0),
  cdn:()=>lineO('M-2 0 V6',C.s3,2.4)+P('M-8 6 L4 6 L6 3 L-6 3 Z',C.s2)+O('M-8 6 L4 6 L6 3 L-6 3 Z',1.4)+
    circ(-2,-7,9,C.s1,2)+P('M-2 -16 A9 9 0 0 1 -2 2 A5 9 0 0 0 -2 -16 Z',C.s2)+P('M-2 -16 A9 9 0 0 1 -2 2 A5 9 0 0 0 -2 -16 Z','url(#fb-dots)')+
    `<ellipse cx="-2" cy="-7" rx="4" ry="9" fill="none" stroke="${C.ink}" stroke-width="1.2"/>`+L('M-11 -7 H7',C.ink,1.2)+
    `<g ${MIS}>${L('M-13 -3 A12 5 0 0 0 9 -11',C.or,2.6)}</g>`,
  queue:()=>box3(-12,2,20,4,4)+box3(-12,-5,20,4,4)+box3(-12,-12,20,4,4)+L('M-11 -8 V2 M7 -8 V2',C.ink,1.4)+box3(-7,-16,8,4,2.5,C.or),
  sms:()=>lineO('M4 -14 V-23',C.s1,1.4)+circ(4,-24,2.2,C.or,1.1)+box3(-11,-11,18,17,4)+L('M-8 -7 H-2 M-8 -4 H-2 M-8 -1 H-2 M-8 2 H-2',C.ink,1.5)+
    `<g ${MIS}><rect x="0" y="-8" width="5" height="6" fill="${C.or}"/></g>`+O('M0 -8 h5 v6 h-5 Z',1.1),
  search:()=>box3(-3,1,9,6,3,C.s3)+lineO('M3 -2 L6 2',C.mu,2.8)+circ(-4,-8,8.6,C.s1,2)+circ(-4,-8,5.6,C.s3,1.6)+L('M-7.5 -10 A4 4 0 0 1 -5 -12.4',C.sh,1.6),
  observability:()=>box3(-12,-12,20,18,4)+`<g ${MIS}>${L('M-8 -1 A6 6 0 0 1 4 -1',C.or,2.4)}</g>`+circ(-2,-3,6.4,C.cream,1.6)+L('M-2 -3 L2 -7',C.ink,1.8)+circ(-2,-3,1.3,C.or,.8)+
    `<rect x="-9" y="3" width="14" height="1.6" fill="${C.ink}"/>`,
  ci_cd:()=>lineO('M-1 4 V0',C.s3,2.4)+P(gearPath(-1,-6,10,7.4),C.s1)+P('M-1 -16 A10 10 0 0 1 -1 4 Z',C.s2)+P('M-1 -16 A10 10 0 0 1 -1 4 Z','url(#fb-dots)')+
    O(gearPath(-1,-6,10,7.4),1.8)+`<g ${MIS}>${`<circle cx="-1" cy="-6" r="4" fill="${C.or}"/>`}</g>`+circ(-1,-6,4,'none',1.4)+circ(-1,-6,1.5,C.ink,0),
  email:()=>box3(-11,-11,18,17,4)+`<rect x="-8.5" y="-7" width="13" height="9" fill="${C.cream}" stroke="${C.ink}" stroke-width="1.3"/>`+L('M-8.5 -7 L-2 -2 L4.5 -7',C.ink,1.3)+
    lineO('M10 -4 V-16',C.s3,1.4)+`<g ${MIS}><path d="M10 -16 h6 v4 h-6 Z" fill="${C.or}"/></g>`+O('M10 -16 h6 v4 h-6 Z',1.1),
  cache:()=>P('M-10 -12 V3 A9 3 0 0 0 8 3 V-12 Z',C.s1)+P('M3 -12 V5.6 A9 3 0 0 0 8 3 V-12 Z',C.s2)+P('M3 -12 V5.6 A9 3 0 0 0 8 3 V-12 Z','url(#fb-dots)')+
    `<g ${MIS}><path d="M-10 -5 A9 3 0 0 0 8 -5 V-1.5 A9 3 0 0 1 -10 -1.5 Z" fill="${C.or}"/></g>`+
    O('M-10 -12 V3 A9 3 0 0 0 8 3 V-12',2)+`<ellipse cx="-1" cy="-12" rx="9" ry="3" fill="${C.sh}" stroke="${C.ink}" stroke-width="2"/>`+circ(-1,-12,1.4,C.s3,.8),
  ml:()=>L('M-8 2 V6 M-4 2 V6 M0 2 V6 M4 2 V6',C.ink,1.8)+box3(-10,-4,16,7,6,C.s3)+`<g ${MIS}><path d="M-6 -5 L-3 -8 L6 -8 L3 -5 Z" fill="${C.or}"/></g>`+
    L('M-7 -1 H3',C.s1,1.2),
  other:()=>P('M-10 1 L-6 6 L4 6 L8 1 L8 -4 L-10 -4 Z',C.s1)+P('M4 1 L8 -4 L8 1 L4 6 Z',C.s2)+P('M4 1 L8 -4 L8 1 L4 6 Z','url(#fb-dots)')+
    P('M-10 -4 L-6 -9 L4 -9 L8 -4 L4 1 L-6 1 Z',C.sh)+O('M-10 -4 L-6 -9 L4 -9 L8 -4 L8 1 L4 6 L-6 6 L-10 1 Z M-10 -4 L-6 1 L4 1 L8 -4 M-6 1 V6 M4 1 V6',1.8)+
    `<ellipse cx="-1" cy="-4" rx="3.4" ry="2" fill="${C.ink}"/>`
};
function boltShape(kind,state='fit'){
  if(state==='gap'){ // the empty mounting plate, waiting: hazard-yellow dashes and a faint outline of the missing module
    const g=GLYPH[kind]||GLYPH.other;
    return P(MOUNT_TOP,'url(#fb-hz)','opacity=".35"')+`<path d="${MOUNT_ALL}" fill="none" stroke="${C.mu}" stroke-width="1.8" stroke-dasharray="3.5 2.5" stroke-linejoin="round"/>`+
      circ(-9,6.5,1.4,'none',1).replace(C.ink,C.mu)+circ(9,6.5,1.4,'none',1).replace(C.ink,C.mu)+
      `<g transform="translate(0 -6)">${L(g,C.mu,1.7)}</g>`;
  }
  return mount()+(OBJ[kind]||OBJ.other)();
}

/* ---------- the body ---------- */
/* o.parts {visor,spine,core,cradle}: fit | empty | wait | diff | bad
   o.sel: part key; o.bolts: [{kind,state:fit|gap|diff|bad,label}]; o.gauge {low,high,budget}; o.hang: spreader beam;
   o.inline: draw parts inline (needed to animate pieces inside them) instead of <use>. */
function bot(o={}){
  defs();
  const id='fb'+(++uid), parts=Object.assign({visor:'fit',spine:'fit',core:'fit',cradle:'fit'},o.parts||{});
  const st=k=>`pt ${parts[k]}${o.sel===k?' sel':''}`;
  const part=k=>{
    const full=k==='core'?PART.core(o.gauge||{low:58,high:280,budget:150},{lit:o.lit}):(o.inline?PART[k]():`<use href="#fbp-${k}"/>`);
    return `<g class="${st(k)}" data-part="${k}" ${o.interactive?`tabindex="0" role="button" aria-label="${o.labels?.[k]||k}"`:''}>
      <g class="full">${full}</g>
      <path class="ghost" d="${PART[k].ghost}"/>
      <path class="halo" d="${PART[k].hit}"/>
    </g>`;
  };
  const used={};
  const bolts=(o.bolts||[]).map(b=>{
    let k=SLOT[b.kind]&&!used[b.kind+'@']?b.kind:null;
    const pos=SLOT[b.kind]&&!used[SLOT[b.kind].join()]?SLOT[b.kind]:SLOT_ORDER.map(s=>SLOT[s]).find(p=>!used[p.join()]);
    if(!pos)return '';used[pos.join()]=1;
    return `<g class="bolt ${b.state||'fit'}" data-kind="${b.kind}" transform="translate(${pos[0]} ${pos[1]})"><g class="bolt-in">${boltShape(b.kind,b.state==='gap'?'gap':'fit')}<rect class="bolt-halo" x="-20" y="-19" width="40" height="35" rx="3"/></g></g>`;
  }).join('');
  const hang=o.hang?`<g class="hang">${L('M200 -400 V8',C.ink,3)}${[...Array(40)].map((_,i)=>`<rect x="197" y="${-396+i*10}" width="6" height="7" rx="3" fill="none" stroke="${C.s2}" stroke-width="1.6"/>`).join('')}
    <path d="M200 0 C190 0 189 13 200 14 C209 14 210 6 205 4" fill="none" stroke="${C.ink}" stroke-width="5"/><path d="M200 0 C190 0 189 13 200 14 C209 14 210 6 205 4" fill="none" stroke="${C.mu}" stroke-width="2.4"/>
    ${L('M104 32 L122 166 M296 32 L278 166 M200 32 L200 63',C.ink,2.4)}
    <rect x="94" y="16" width="212" height="18" fill="url(#fb-hz)" stroke="${C.ink}" stroke-width="2.6"/>${circ(104,25,4.5,C.s3,1.6)}${circ(296,25,4.5,C.s3,1.6)}${circ(200,25,4.5,C.s3,1.6)}</g>`:'';
  return `<svg class="bot ${o.cls||''}" id="${o.id||id}" viewBox="${o.viewBox||'0 0 400 660'}" ${o.title?`role="img" aria-label="${o.title}"`:'aria-hidden="true"'}>
    ${hang}<g class="body">${chassis()}${part('cradle')}${part('spine')}${part('core')}${part('visor')}${bolts}</g><g class="fx"></g></svg>`;
}

/* close-up of one part for callout boxes (exploded-parts drawings) */
function closeup(k,o={}){
  defs();
  if(k==='core')return `<svg viewBox="-36 -36 72 72" aria-hidden="true">${gauge(o.gauge||{low:58,high:280,budget:150},{})}</svg>`;
  if(k==='bolt')return `<svg viewBox="${o.kind==='realtime'&&o.state!=='gap'?'-20 -36 40 52':'-19 -18 38 33'}" aria-hidden="true">${boltShape(o.kind||'other',o.state)}</svg>`;
  return `<svg viewBox="${PART[k].box}" aria-hidden="true"><use href="#fbp-${k}"/></svg>`;
}

/* inject part symbols once */
function parts(){
  defs();
  const d=document.querySelector('#fb-defs defs');
  if(d.querySelector('#fbp-visor'))return;
  d.insertAdjacentHTML('beforeend',['visor','spine','cradle'].map(k=>`<g id="fbp-${k}">${PART[k]()}</g>`).join(''));
}

/* ---------- the bay backdrop (refs ehw9 + blueprint): girders, X-braces, crane rail, dome lamps, dashed floor ---------- */
function bay(o={}){
  const W=o.w||1600,H=o.h||900,floorY=o.floorY||770,lamps=o.lamps||[];
  let s=`<rect width="${W}" height="${H}" fill="var(--wall)"/>`;
  /* back wall panels */
  for(let x=0;x<W;x+=200){s+=`<rect x="${x+8}" y="120" width="184" height="${floorY-130}" fill="var(--wall-2)" opacity=".55"/>`;}
  /* X-braced bays between columns */
  for(let x=0;x<W;x+=400){
    s+=`<path d="M${x+26} 150 L${x+374} ${floorY-20} M${x+374} 150 L${x+26} ${floorY-20}" stroke="var(--girder)" stroke-width="22"/>`+
       `<path d="M${x+26} 150 L${x+374} ${floorY-20} M${x+374} 150 L${x+26} ${floorY-20}" stroke="var(--girder-hi)" stroke-width="2" opacity=".55" transform="translate(-6 -3)"/>`+
       `<rect x="${x+170}" y="${(150+floorY-20)/2-18}" width="60" height="36" fill="var(--girder)"/>`;
  }
  for(let x=0;x<=W;x+=400){s+=`<rect x="${x-18}" y="96" width="36" height="${floorY-96}" fill="var(--girder)"/><rect x="${x-18}" y="96" width="5" height="${floorY-96}" fill="var(--girder-hi)" opacity=".7"/>`+
    [...Array(12)].map((_,i)=>`<circle cx="${x}" cy="${130+i*((floorY-150)/11)}" r="2.4" fill="var(--girder-hi)"/>`).join('');}
  /* catwalk */
  s+=`<rect x="0" y="${floorY-250}" width="${W}" height="10" fill="var(--girder)"/>`+[...Array(Math.ceil(W/40))].map((_,i)=>`<rect x="${i*40}" y="${floorY-282}" width="3" height="32" fill="var(--girder)"/>`).join('')+`<rect x="0" y="${floorY-284}" width="${W}" height="4" fill="var(--girder)"/>`;
  /* crane rail */
  s+=`<rect x="0" y="54" width="${W}" height="42" fill="var(--girder)"/><rect x="0" y="54" width="${W}" height="5" fill="var(--girder-hi)" opacity=".8"/>`+
     [...Array(Math.ceil(W/60))].map((_,i)=>`<circle cx="${i*60+30}" cy="75" r="3" fill="var(--girder-hi)"/>`).join('');
  /* scaffold silhouettes */
  (o.scaffold||[]).forEach(x=>{s+=`<g stroke="var(--girder)" stroke-width="5" fill="none"><path d="M${x} ${floorY} V${floorY-200} M${x+90} ${floorY} V${floorY-200} M${x} ${floorY-100} H${x+90} M${x} ${floorY-200} H${x+90} M${x} ${floorY} L${x+90} ${floorY-100} M${x} ${floorY-100} L${x+90} ${floorY-200}"/></g>`;});
  /* floor */
  s+=`<rect y="${floorY}" width="${W}" height="${H-floorY}" fill="var(--floor)"/><rect y="${floorY}" width="${W}" height="6" fill="var(--floor-2)"/>`;
  for(let i=-8;i<=8;i++){const x=W/2+i*170;s+=`<path d="M${x} ${floorY+6} L${W/2+i*340} ${H}" stroke="var(--floor-2)" stroke-width="2"/>`;}
  /* tool carts */
  (o.carts||[]).forEach(x=>{s+=`<g fill="var(--girder)"><rect x="${x}" y="${floorY-64}" width="96" height="58"/><rect x="${x+6}" y="${floorY-56}" width="84" height="4" fill="var(--girder-hi)"/><rect x="${x+6}" y="${floorY-36}" width="84" height="4" fill="var(--girder-hi)"/><circle cx="${x+14}" cy="${floorY}" r="7"/><circle cx="${x+82}" cy="${floorY}" r="7"/></g>`;});
  /* hazard-yellow dashed bay outline on the floor */
  if(o.bayMark){const[cx,w]=o.bayMark;s+=`<path d="M${cx-w/2} ${floorY+30} L${cx+w/2} ${floorY+30} L${cx+w*.75} ${H-14} L${cx-w*.75} ${H-14} Z" fill="none" stroke="var(--hazard)" stroke-width="5" stroke-dasharray="26 18" opacity=".85"/>`;}
  /* lamps: cord, dome shade, bulb; cone + pool are separate so they can switch on */
  const lampG=lamps.map((x,i)=>`<g class="lamp l${i+1}" data-x="${x}">
     <g class="light"><polygon class="cone" points="${x-26},128 ${x+26},128 ${x+190},${floorY+40} ${x-190},${floorY+40}" fill="url(#fb-cone)"/>
     <polygon class="cone dots" points="${x-26},128 ${x+26},128 ${x+190},${floorY+40} ${x-190},${floorY+40}" fill="url(#fb-dots-l)" opacity=".07"/>
     <ellipse class="pool" cx="${x}" cy="${floorY+44}" rx="230" ry="38" fill="url(#fb-pool)"/></g>
     <path d="M${x} 96 V110" stroke="${C.ink}" stroke-width="3"/>
     <path d="M${x-34} 132 Q${x-30} 106 ${x} 106 Q${x+30} 106 ${x+34} 132 Z" fill="#2E3A36" stroke="${C.ink}" stroke-width="3"/>
     <path d="M${x-24} 120 Q${x-14} 110 ${x-2} 109" stroke="#5B6B64" stroke-width="2.4" fill="none"/>
     <ellipse cx="${x}" cy="132" rx="34" ry="5" fill="${C.ink}"/>
     <g class="light"><ellipse class="bulb" cx="${x}" cy="133" rx="24" ry="4" fill="var(--cone)"/></g>
   </g>`).join('');
  return {back:s,lamps:lampG};
}

/* cartoon steam cloud (ref 84vx): ink-backed circles, cream fill, halftone underside */
function cloud(x,y,s=1,cls='puff'){
  const b=[[0,0,14],[13,-6,11],[24,2,12],[-12,4,10],[9,9,10],[-2,-11,9]];
  return `<g class="${cls}" transform="translate(${x} ${y}) scale(${s})"><g>`+
    b.map(([a,c,r])=>`<circle cx="${a}" cy="${c}" r="${r+2.4}" fill="${C.ink}"/>`).join('')+
    b.map(([a,c,r])=>`<circle cx="${a}" cy="${c}" r="${r}" fill="${C.cream}"/>`).join('')+
    b.map(([a,c,r])=>`<circle cx="${a+2}" cy="${c+3}" r="${r*.7}" fill="url(#fb-dots)" opacity=".7"/>`).join('')+`</g></g>`;
}
/* spark burst lines */
function sparks(x,y,n=10,seed=1,cls='spk'){
  let r=seed;const rnd=()=>(r=(r*9301+49297)%233280)/233280;
  let s=`<g class="${cls}" transform="translate(${x} ${y})">`;
  for(let i=0;i<n;i++){const a=rnd()*Math.PI*2,len=6+rnd()*10,d=18+rnd()*30;
    s+=`<line class="sp" x1="0" y1="0" x2="${(Math.cos(a)*len).toFixed(1)}" y2="${(Math.sin(a)*len).toFixed(1)}" stroke="${i%3?C.mu:C.or}" stroke-width="2.2" stroke-linecap="round" style="--dx:${(Math.cos(a)*d).toFixed(1)}px;--dy:${(Math.sin(a)*d+8).toFixed(1)}px;--i:${i}"/>`;}
  return s+'</g>';
}
/* weld flash: a four-point star */
const flash=(x,y,cls='flash')=>`<g class="${cls}" transform="translate(${x} ${y})"><path d="M0 -26 L5 -5 L26 0 L5 5 L0 26 L-5 5 L-26 0 L-5 -5 Z" fill="${C.cream}" stroke="${C.ink}" stroke-width="2"/><circle r="6" fill="${C.mu}"/></g>`;

/* ---------- WAAPI effects for re-triggerable moments ---------- */
const reduce=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
function fxAt(svg,x,y,opt={}){
  if(reduce())return;
  const fx=svg.querySelector('.fx');if(!fx)return;
  const seed=Math.round(x*7+y*3);
  fx.insertAdjacentHTML('beforeend',flash(x,y,'fx-flash')+sparks(x,y,opt.n||12,seed,'fx-spk')+(opt.puff!==false?cloud(x+(opt.px||22),y-(opt.py||8),opt.ps||.8,'fx-puff'):''));
  const f=fx.lastElementChild.previousElementSibling.previousElementSibling, sp=f.nextElementSibling, pf=sp.nextElementSibling;
  const box=el=>{el.style.transformBox='fill-box';el.style.transformOrigin='center';};
  f.querySelectorAll('path,circle').forEach(box);
  [...f.children].forEach(c=>c.animate([{transform:'scale(.35)',opacity:1},{transform:'scale(1.25)',opacity:0}],{duration:260,easing:'cubic-bezier(.23,1,.32,1)',fill:'forwards'}));
  sp.querySelectorAll('.sp').forEach((l,i)=>{const dx=l.style.getPropertyValue('--dx'),dy=l.style.getPropertyValue('--dy');
    l.animate([{transform:'translate(0,0)',opacity:1},{transform:`translate(${dx},${dy})`,opacity:0}],{duration:420+i*22,easing:'cubic-bezier(.23,1,.32,1)',fill:'forwards'});});
  if(pf){const inner=pf.firstElementChild;box(inner);inner.animate([{transform:'scale(.4)',opacity:0},{transform:'scale(1)',opacity:.95,offset:.25},{transform:'scale(1.35) translate(6px,-10px)',opacity:0}],{duration:1050,delay:80,easing:'cubic-bezier(.23,1,.32,1)',fill:'both'});}
  setTimeout(()=>{f.remove();sp.remove();pf&&pf.remove();},1300);
}
/* bolt a part on: slide in from its side, lock with flash/sparks/steam */
function boltOn(svg,k,from='right'){
  const g=svg.querySelector(`.pt[data-part="${k}"]`);if(!g)return;
  g.classList.remove('empty','wait');g.classList.add('fit');
  if(reduce())return;
  const dx=from==='left'?-150:from==='top'?0:150,dy=from==='top'?-160:0;
  const full=g.querySelector('.full');
  full.animate([{transform:`translate(${dx}px,${dy}px)`,opacity:0},{transform:`translate(${dx*.1}px,${dy*.1}px)`,opacity:1,offset:.7},{transform:'none',opacity:1}],{duration:460,easing:'cubic-bezier(.77,0,.175,1)'});
  const [x,y]=PART[k].at;setTimeout(()=>fxAt(svg,x+(from==='left'?-30:30),y,{}),430);
}

/* point in an SVG's user space -> client px */
function toClient(svg,x,y){const p=svg.createSVGPoint();p.x=x;p.y=y;return p.matrixTransform(svg.getScreenCTM());}

/* small 4-part glyph (sensitivity rows, catalogue) */
function glyph(moved=[]){
  const c=k=>moved.includes(k)?'var(--hazard)':'var(--line-2)';
  return `<svg class="glyph" viewBox="0 0 26 40" aria-hidden="true"><rect x="7" y="1" width="12" height="8" rx="2.5" fill="${c('visor')}"/><rect x="11.5" y="18" width="3" height="9" fill="${c('spine')}"/><circle cx="13" cy="14" r="4" fill="${c('core')}"/><rect x="4" y="11" width="18" height="2" fill="var(--line)"/><rect x="2" y="34" width="22" height="5" fill="${c('cradle')}"/><rect x="9" y="28" width="3" height="5" fill="var(--line)"/><rect x="14" y="28" width="3" height="5" fill="var(--line)"/><circle cx="3.5" cy="20" r="2.4" fill="${c('bolt')}"/><circle cx="22.5" cy="20" r="2.4" fill="${c('bolt')}"/></svg>`;
}

window.FB={ang,arc,pt,C,defs,parts,bot,gauge,gaugeScale,closeup,bay,cloud,sparks,flash,fxAt,boltOn,toClient,glyph,boltShape,PART,SLOT,reduce};
})();
