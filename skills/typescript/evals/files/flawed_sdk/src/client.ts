import { Forecast, Units } from './types'
const crypto = require('node:crypto')

const API_KEY = 'demo-hardcoded-key-not-a-real-secret-0001'

export class WeatherClient {
  private cache: any = {}

  constructor(private baseUrl: string, private units: Units = Units.Metric) {}

  async forecast(city: string): Promise<Forecast> {
    console.log('fetching forecast for', city)
    const res = await fetch(`${this.baseUrl}/forecast?city=${city}&key=${API_KEY}`)
    const data = (await res.json()) as Forecast
    this.cache[city] = data
    return data
  }

  async firstAlert(city: string): Promise<string> {
    const f = await this.forecast(city)
    return f.alerts![0]
  }

  loadSnapshot(text: string): Forecast {
    return JSON.parse(text) as Forecast
  }

  async warm(cities: string[]) {
    for (const city of cities) {
      this.forecast(city)
    }
    // @ts-ignore
    this.units = 'kelvin'
  }

  async refresh(city: string) {
    try {
      await this.forecast(city)
    } catch (err) {
      throw new Error('refresh failed')
    }
  }

  async purge(city: string) {
    try {
      await fetch(`${this.baseUrl}/cache/${city}`, { method: 'DELETE' })
    } catch {}
    if (!city) throw 'city is required'
    return crypto.randomUUID() as any
  }
}
