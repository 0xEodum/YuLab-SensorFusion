// Import-only evaluator for the allowlisted static model components. No React renderer,
// frame callbacks, effects, controls or application entrypoints execute.
export const Fragment = Symbol("fragment");
export const createElement = (type, props, ...children) => ({
  type,
  props: { ...props, children },
});
export const jsx = (type, props) => ({ type, props });
export const jsxs = jsx;
export const useMemo = (build) => build();
export const useRef = (value) => ({ current: value });
export const useEffect = () => {};
export const useLayoutEffect = () => {};
export const useFrame = () => {};
export const useState = (value) => [typeof value === "function" ? value() : value, () => {}];
export const createContext = (value) => {
  const context = { value };
  context.Provider = ({ value: next, children }) => {
    context.value = next;
    return children;
  };
  return context;
};
export const useContext = (context) => context.value;
export default { createElement, Fragment };
