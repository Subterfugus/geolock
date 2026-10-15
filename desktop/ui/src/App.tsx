import { useStore } from './lib/store';
import { BootError, FatalError, Splash } from './components/Splash';
import { SetupScreen } from './components/Setup';
import { Shell } from './components/Shell';

/** Chooses the screen: splash while the engine starts, onboarding on first run, otherwise the main window. */
export function App() {
  const reachable = useStore((s) => s.reachable);
  const bootTimedOut = useStore((s) => s.bootTimedOut);
  const state = useStore((s) => s.status?.state);
  const setupSeen = useStore((s) => s.setupSeen);
  if (!reachable) return bootTimedOut ? <BootError /> : <Splash />;
  if (state === 'error') return <FatalError />;
  const inSetup = state === 'needs_setup' || state === 'setting_up' || (state === 'loading' && setupSeen);
  if (inSetup) return <SetupScreen />;
  return <Shell />;
}
