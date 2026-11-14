/** Full-screen boot state (old index.html .td-boot) while the session / admin check runs. */
import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/shell.css";
import { useTheme } from "../lib/prefs";
import markNavy from "./brand/mark-navy.svg";
import markWhite from "./brand/mark-white.svg";

export function PortalBoot() {
  const theme = useTheme();
  return (
    <div className="tdp" data-tdp-theme={theme}>
      <div className="td-boot" aria-busy="true" role="status">
        <img className="td-logo-navy" src={markNavy} alt="" width={72} height={72} />
        <img className="td-logo-white" src={markWhite} alt="" width={72} height={72} />
        <span className="td-boot__bar" aria-hidden="true">
          <span />
        </span>
        <span className="td-sr-only">Loading the outreach portal…</span>
      </div>
    </div>
  );
}
