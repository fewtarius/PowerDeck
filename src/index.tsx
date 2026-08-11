import {
  definePlugin,
  staticClasses,
} from "@decky/ui";
import { FaBolt } from "react-icons/fa";

import { Content } from "./components/Content";
import { ErrorBoundary } from "./components/ErrorBoundary";

const index = definePlugin(() => ({
  title: <div className={staticClasses.Title}>PowerDeck</div>,
  content: (
    <ErrorBoundary>
      <Content />
    </ErrorBoundary>
  ),
  icon: <FaBolt />,
}));

export default index;
