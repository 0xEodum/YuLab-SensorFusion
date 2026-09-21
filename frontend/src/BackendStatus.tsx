import { useEffect, useState } from 'react';
import { parseJson, validatePayload } from '@yulab/contracts';
import './backend-status.css';

type Connection = { phase: 'connecting' | 'online' | 'offline'; message: string };

export default function BackendStatus() {
  const [attempt, setAttempt] = useState(0);
  const [connection, setConnection] = useState<Connection>({ phase: 'connecting', message: 'Connecting to lab backend…' });
  useEffect(() => {
    const timer = setInterval(() => setAttempt(value => value + 1), 15_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 3000);
    async function connect() {
      try {
        const responses = await Promise.all(['health', 'capabilities'].map(path => fetch(`/api/v1/${path}`, { signal: controller.signal, cache: 'no-store' })));
        if (responses.some(response => !response.ok)) throw new Error('Backend unavailable');
        const [health, capabilities] = await Promise.all(responses.map(async response => parseJson(await response.text())));
        try {
          validatePayload('Health', health);
          validatePayload('Capabilities', capabilities);
        } catch {
          if (active) setConnection({ phase: 'offline', message: 'Backend response is incompatible. Update the app and backend together.' });
          return;
        }
        // Foundation status comes from the provider, never from a mock response.
        const enabled = Object.values(capabilities.sensors).some(sensor => sensor.available);
        if (active) setConnection({ phase: 'online', message: enabled ? 'Backend connected · Sensor services available' : 'Backend connected · Sensor capture and training are not implemented yet' });
      } catch {
        if (active) setConnection({ phase: 'offline', message: 'Backend unavailable · Terrain editing and exports still work' });
      } finally {
        clearTimeout(timeout);
      }
    }
    void connect();
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [attempt]);

  return <aside className={`backend-status ${connection.phase}`} aria-label="Lab backend">
    <span role="status"><span className="backend-dot" aria-hidden="true" />{connection.message}</span>
    <button type="button" onClick={() => setAttempt(value => value + 1)}>{connection.phase === 'offline' ? 'Retry connection' : 'Check connection'}</button>
  </aside>;
}
