export enum Units {
  Metric = 'metric',
  Imperial = 'imperial',
}

export namespace Weather {
  export const DEFAULT_CITY = 'Bogota'
}

export interface Forecast {
  city: string
  tempC: number
  alerts?: string[]
}
