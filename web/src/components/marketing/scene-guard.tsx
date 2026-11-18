"use client";

import { Component, type ReactNode } from "react";

/**
 * A 3D scene is decoration. If it cannot load (a blocked file, a failed
 * decoder, a lost GPU context) the page must carry on without it, so the
 * error is caught here and the fallback is drawn instead.
 */
export class SceneGuard extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
