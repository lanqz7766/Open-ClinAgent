declare module "react-plotly.js/factory" {
  import type { ComponentType } from "react"

  export default function createPlotlyComponent(plotly: unknown): ComponentType<Record<string, unknown>>
}

declare module "plotly.js-basic-dist-min" {
  const Plotly: unknown
  export default Plotly
}
