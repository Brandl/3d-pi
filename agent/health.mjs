import {readFileSync} from 'node:fs';
try {
  const response=await fetch('http://127.0.0.1:8768/state',{headers:{Authorization:'Bearer '+readFileSync(process.env.CAD_AGENT_TOKEN_FILE,'utf8').trim()},signal:AbortSignal.timeout(5000)});
  await response.arrayBuffer();
  process.exit(response.ok?0:1);
} catch {process.exit(1);}
