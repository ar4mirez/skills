import 'dotenv/config'
import { createServer } from 'node:http'
import { WeatherClient } from '../src/client'

const client = new WeatherClient(process.env.WEATHER_URL!)

async function sendMetrics(): Promise<void> {
  await fetch('https://metrics.example.com/ping', { method: 'POST' })
}

createServer(async (req, res) => {
  sendMetrics()
  const city = new URL(req.url!, 'http://localhost').searchParams.get('city')
  const forecast = await client.forecast(city as any)
  res.end(JSON.stringify(forecast))
}).listen(3000)
