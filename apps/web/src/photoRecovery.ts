export type PhotoReference = {schema:1; key:string; hash:string};

// No photograph, file name, location or image metadata is persisted.
export function parsePhotoReference(raw:string):PhotoReference {
  const value=JSON.parse(raw);
  if(value?.schema!==1 || typeof value.key!=='string' || !/^[a-zA-Z0-9-]{8,100}$/.test(value.key) || typeof value.hash!=='string' || !/^[a-f0-9]{64}$/.test(value.hash))throw new Error('Invalid photo recovery reference');
  return {schema:1,key:value.key,hash:value.hash};
}

export async function photoHash(file:Blob):Promise<string> {
  const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
  return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
}
