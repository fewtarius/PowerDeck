import { Component, ErrorInfo, ReactNode } from "react";
import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";

interface PowerDeckErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, PowerDeckErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): PowerDeckErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[PowerDeck] UI error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <PanelSection title="PowerDeck - Error">
          <PanelSectionRow>
            <div style={{ padding: 16, color: "#ff6b6b" }}>
              <div style={{ marginBottom: 8 }}>PowerDeck hit an error. Recovering in 5s...</div>
              <div style={{ fontSize: "0.8em", color: "#888" }}>
                {this.state.error?.message || "Unknown error"}
              </div>
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Retry Now
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      );
    }
    return this.props.children;
  }
}
