import { inject, watch, type InjectionKey, type Ref } from 'vue';
import type { BackendStatus } from '../../../desktop/bridge-contract.js';

export const backendConnectionKey: InjectionKey<Readonly<Ref<BackendStatus>>> = Symbol('backend-connection');

// Refresh failed reads when the connection returns without remounting editors
// or losing their unsaved form values. Vue disposes this watcher with its owner.
export function onBackendConnected(refresh: () => void): void {
  const status = inject(backendConnectionKey, undefined);
  if (!status) return;
  watch(() => status.value.state, (current, previous) => {
    if (current === 'connected' && previous !== 'connected') refresh();
  });
}
