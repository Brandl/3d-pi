import {test,expect} from '@playwright/test';

for(const software of [false,true])test(`dedicated centered white 3D thumbnails (${software?'software':'WebGL'})`,async({page})=>{
 if(software)await page.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type:string,...args:unknown[]){return type.includes('webgl')?null:Reflect.apply(get,this,[type,...args]);} as typeof get;});
 await page.goto('/');
 const image=page.locator('#history .current .revision-thumb');
 await expect(image).toHaveAttribute('data-rendered','true',{timeout:30000});
 const pixels=await image.evaluate(async(el:HTMLImageElement)=>{
  await el.decode();const canvas=document.createElement('canvas');canvas.width=el.naturalWidth;canvas.height=el.naturalHeight;const ctx=canvas.getContext('2d')!;ctx.drawImage(el,0,0);const {data}=ctx.getImageData(0,0,canvas.width,canvas.height);
  let minX=canvas.width,maxX=0,minY=canvas.height,maxY=0,count=0;
  for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){const i=(y*canvas.width+x)*4;if(Math.min(data[i],data[i+1],data[i+2])<245){minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);count++;}}
  const corners=[0,(canvas.width-1)*4,(canvas.height-1)*canvas.width*4,(canvas.width*canvas.height-1)*4].map(i=>Array.from(data.slice(i,i+4)));
  return {corners,minX,maxX,minY,maxY,count,width:canvas.width,height:canvas.height};
 });
 expect(pixels.corners).toEqual(Array(4).fill([255,255,255,255]));
 expect(pixels.count).toBeGreaterThan(1000);
 expect(Math.abs(pixels.minX-(pixels.width-1-pixels.maxX))).toBeLessThan(4);
 expect(Math.abs(pixels.minY-(pixels.height-1-pixels.maxY))).toBeLessThan(4);
 expect(pixels.minX).toBeGreaterThan(6);expect(pixels.minY).toBeGreaterThan(6);
 await image.screenshot({path:`test-results/thumbnail-${software?'software':'webgl'}.png`});
});
