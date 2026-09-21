// Small inline formatter. All content uses DOM text nodes, never HTML parsing.
export function formatChatText(target:HTMLElement,text:string){
 const tokens=text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\((?:https?:\/\/|\/)[^\s)]+\))/g);
 for(const token of tokens){
  if(token.startsWith('**')&&token.endsWith('**')&&token.length>4){const strong=document.createElement('strong');strong.textContent=token.slice(2,-2);target.append(strong);}
  else if(token.startsWith('`')&&token.endsWith('`')&&token.length>2){const code=document.createElement('code');code.textContent=token.slice(1,-1);target.append(code);}
  else {const link=token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);if(link){
   let url:URL;try{url=new URL(link[2],location.origin);}catch{target.append(document.createTextNode(token));continue;}
   if(['http:','https:'].includes(url.protocol)){const a=document.createElement('a');a.textContent=link[1];a.href=url.href;if(url.origin!==location.origin){a.target='_blank';a.rel='noopener noreferrer';}target.append(a);continue;}
  }target.append(document.createTextNode(token));}
 }
}
