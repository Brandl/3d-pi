export const projectId = new URL(location.href).searchParams.get('project');
if (projectId && !/^[a-z0-9][a-z0-9-]{0,63}$/.test(projectId)) throw new Error('Invalid project ID');
export function projectPath(path: string) {
  return projectId && (path.startsWith('/api/') || path.startsWith('/downloads/'))
    ? `/projects/${projectId}${path}` : path;
}
