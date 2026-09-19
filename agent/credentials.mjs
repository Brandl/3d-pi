import {readFileSync} from 'node:fs';

// The host owns OAuth refresh. Never invoke a refresh callback for a shared
// credential: two independent writers could invalidate rotating refresh tokens.
export class ReadOnlyCredentialStore {
  constructor(path,provider) {this.path=path;this.provider=provider;}
  async read(provider) {
    if(provider!==this.provider)return undefined;
    const credential=JSON.parse(readFileSync(this.path,'utf8'))[provider];
    if(credential?.type==='oauth' && credential.expires<=Date.now()+60000)return undefined;
    return credential;
  }
  async list() {
    const credential=await this.read(this.provider);
    return credential?[{providerId:this.provider,type:credential.type}]:[];
  }
  async modify() {throw new Error('Read-only provider login: renew the login on its owning host');}
  async delete() {throw new Error('Read-only provider login');}
}
