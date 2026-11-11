export type Surface = "demo" | "dev"

export function withSurfacePath(surface: Surface, path: string) {
  const normalized = path.startsWith("/") ? path : `/${path}`
  return `/${surface}${normalized === "/" ? "" : normalized}`
}

export function stripSurfacePrefix(pathname: string) {
  if (pathname === "/demo" || pathname === "/dev") {
    return "/"
  }
  if (pathname.startsWith("/demo/")) {
    return pathname.slice("/demo".length)
  }
  if (pathname.startsWith("/dev/")) {
    return pathname.slice("/dev".length)
  }
  return pathname || "/"
}
