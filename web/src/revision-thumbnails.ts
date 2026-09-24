import * as THREE from 'three';
import {projectPath} from './project-path';

type Part={vertices:number[][];triangles:number[][];color?:string;opacity?:number};
type Preview={parts:Part[]};
const width=320,height=200;
const cache=new Map<string,string>();
const queue:{image:HTMLImageElement;revision:string}[]=[];
let running=false;
let renderer:THREE.WebGLRenderer|null|undefined;

// A single renderer, a serial queue, and a bounded bitmap cache. Never rebuild CAD.
function renderThumbnail(data:Preview):string{
 const parts=data.parts.filter(p=>p.vertices.length&&p.triangles.length);
 if(!parts.length||parts.reduce((n,p)=>n+p.triangles.length,0)>1000000)throw Error('Thumbnail geometry unavailable or over budget');
 const bounds=new THREE.Box3();
 for(const part of parts)for(const v of part.vertices){if(v.length!==3||!v.every(Number.isFinite))throw Error('Invalid preview vertex');bounds.expandByPoint(new THREE.Vector3(...v));}
 const center=bounds.getCenter(new THREE.Vector3());
 const normal=new THREE.Vector3(1,-1.3,1).normalize();
 const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,0,1),normal).normalize();
 const up=new THREE.Vector3().crossVectors(normal,right).normalize();
 let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
 for(const part of parts)for(const v of part.vertices){const d=new THREE.Vector3(...v).sub(center);const x=d.dot(right),y=d.dot(up);minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
 center.addScaledVector(right,(minX+maxX)/2).addScaledVector(up,(minY+maxY)/2);
 const halfHeight=Math.max((maxY-minY)/2,(maxX-minX)*height/width/2,0.001)*1.16,halfWidth=halfHeight*width/height;
 if(renderer===undefined){try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});renderer.setSize(width,height);renderer.setPixelRatio(1);renderer.setClearColor(0xffffff,1);renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;}catch{renderer=null;}}
 if(renderer?.getContext().isContextLost()){renderer.dispose();renderer=null;}
 if(renderer){
  const scene=new THREE.Scene();scene.background=new THREE.Color('white');
  scene.add(new THREE.HemisphereLight(0xffffff,0x9a9fa5,2.1));
  const light=new THREE.DirectionalLight(0xffffff,2.6);light.position.set(1,-2,4);scene.add(light);
  const distance=Math.max(bounds.getSize(new THREE.Vector3()).length(),1)*3;
  const camera=new THREE.OrthographicCamera(-halfWidth,halfWidth,halfHeight,-halfHeight,0.01,distance*3);
  camera.up.set(0,0,1);camera.position.copy(center).addScaledVector(normal,distance);camera.lookAt(center);
  const resources:{geometry:THREE.BufferGeometry;material:THREE.MeshStandardMaterial}[]=[];
  try{
   for(const part of parts){
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(part.vertices.flat(),3));geometry.setIndex(part.triangles.flat());geometry.computeVertexNormals();
    const opacity=part.opacity??1;
    const material=new THREE.MeshStandardMaterial({color:part.color??'#92a4b6',roughness:.75,metalness:0,side:THREE.DoubleSide,opacity,transparent:opacity<1});
    resources.push({geometry,material});scene.add(new THREE.Mesh(geometry,material));
   }
   renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png');
  }finally{for(const r of resources){r.geometry.dispose();r.material.dispose();}renderer.renderLists.dispose();}
 }
 // Orthographic software fallback: actual projected, depth-sorted mesh triangles,
 // not a screenshot, background substitution, or a different revision's image.
 if(parts.reduce((n,p)=>n+p.triangles.length,0)>100000)throw Error('Software thumbnail budget exceeded');
 const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
 const ctx=canvas.getContext('2d')!;ctx.fillStyle='#ffffff';ctx.fillRect(0,0,width,height);
 const triangles:{points:number[][];depth:number;color:string;opacity:number}[]=[];
 const light=new THREE.Vector3(1,-2,4).normalize();
 for(const part of parts){
  const vertices=part.vertices.map(v=>{const p=new THREE.Vector3(...v).sub(center);return [(p.dot(right)/halfWidth+1)*width/2,(1-p.dot(up)/halfHeight)*height/2,p.dot(normal)];});
  for(const indices of part.triangles){
   const points=indices.map(i=>vertices[i]);if(points.some(p=>!p))throw Error('Invalid triangle');
   const [a,b,c]=indices.map(i=>new THREE.Vector3(...part.vertices[i]));
   const n=b.sub(a).cross(c.sub(a)).normalize();
   const shade=.48+.38*Math.abs(n.dot(light));
   const color=new THREE.Color(part.color??'#92a4b6').multiplyScalar(shade).getStyle();
   triangles.push({points,depth:points.reduce((s,p)=>s+p[2],0)/3,color,opacity:part.opacity??1});
  }
 }
 triangles.sort((a,b)=>a.depth-b.depth);
 for(const triangle of triangles){ctx.globalAlpha=triangle.opacity;ctx.fillStyle=triangle.color;ctx.beginPath();triangle.points.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fill();}
 return canvas.toDataURL('image/png');
}

async function fetchPreview(revision:string){
 const response=await fetch(projectPath(`/api/revisions/${revision}/artifacts/preview.json`),{credentials:'same-origin',signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw Error('Preview unavailable');
 const reader=response.body!.getReader();const chunks:Uint8Array[]=[];let size=0;
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>64*1024*1024){await reader.cancel();throw Error('Preview exceeds thumbnail budget');}chunks.push(value);}
 const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 return JSON.parse(new TextDecoder().decode(bytes)) as Preview;
}
async function drain(){
 if(running)return;running=true;
 try{while(queue.length){
  const item=queue.shift()!;if(!item.image.isConnected)continue;
  const rect=item.image.getBoundingClientRect();
  const clip=item.image.closest('#history')?.getBoundingClientRect();
  if(!item.image.getClientRects().length||rect.bottom<0||rect.top>innerHeight||(clip&&(rect.right<clip.left||rect.left>clip.right))){observer.observe(item.image);continue;}
  const key=projectPath(item.revision);
  try{
   let bitmap=cache.get(key);
   if(!bitmap){const data=await fetchPreview(item.revision);if(!item.image.isConnected)continue;bitmap=renderThumbnail(data);cache.set(key,bitmap);if(cache.size>48)cache.delete(cache.keys().next().value!);}
   if(item.image.isConnected){item.image.src=bitmap;item.image.dataset.rendered='true';}
  }catch{if(item.image.isConnected){item.image.hidden=true;item.image.parentElement?.classList.add('thumb-unavailable');}}
  await new Promise(resolve=>setTimeout(resolve,30));
 }}finally{running=false;}
}
const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){const image=entry.target as HTMLImageElement;observer.unobserve(image);queue.push({image,revision:image.dataset.revision!});}void drain();},{rootMargin:'0px 140px'});
export function revisionThumbnail(revision:string){
 const image=document.createElement('img');image.className='revision-thumb';image.alt='';image.width=width;image.height=height;image.decoding='async';image.dataset.revision=revision;
 // White placeholder, never an old dark review screenshot.
 image.src='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="200"%3E%3Cpath fill="white" d="M0 0h320v200H0z"/%3E%3C/svg%3E';
 observer.observe(image);return image;
}
export function resetThumbnailQueue(){observer.disconnect();queue.length=0;requestAnimationFrame(()=>document.querySelectorAll<HTMLImageElement>('.revision-thumb:not([data-rendered])').forEach(image=>{if(!image.hidden&&image.dataset.revision)observer.observe(image);}));}
