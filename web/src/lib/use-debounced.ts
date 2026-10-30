import { useEffect, useState } from "react";

/** `value`, but only once it has stopped changing for `ms`. Used so that
 *  typing a risk of 1.25 asks the server once, not for "1", "1." and "1.2". */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
