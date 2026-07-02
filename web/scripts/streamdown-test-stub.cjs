const React = require("react");

function passthroughPlugin() {
  return {};
}

function Streamdown({ children }) {
  return React.createElement(React.Fragment, null, children);
}

module.exports = {
  Streamdown,
  cjk: passthroughPlugin,
  code: passthroughPlugin,
  math: passthroughPlugin,
  mermaid: passthroughPlugin,
};
