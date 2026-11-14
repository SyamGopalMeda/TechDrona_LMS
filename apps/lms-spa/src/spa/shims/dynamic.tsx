/** `next/dynamic` → React.lazy + Suspense (the SPA renders on the client only, so `ssr` is moot). */
import { lazy, Suspense, type ComponentType, type ReactNode } from "react";

type Loaded<P> = ComponentType<P> | { default: ComponentType<P> };

export interface DynamicOptions {
  ssr?: boolean;
  loading?: (props: { isLoading?: boolean; pastDelay?: boolean; error?: Error | null }) => ReactNode;
}

export default function dynamic<P extends object>(loader: () => Promise<Loaded<P>>, options: DynamicOptions = {}): ComponentType<P> {
  const Lazy = lazy(async () => {
    const m = await loader();
    return { default: (typeof m === "object" && m !== null && "default" in m ? m.default : m) as ComponentType<P> };
  });
  const Loading = options.loading;
  const LazyAny = Lazy as unknown as ComponentType<P>;
  function DynamicComponent(props: P) {
    return (
      <Suspense fallback={Loading ? <Loading isLoading pastDelay error={null} /> : null}>
        <LazyAny {...props} />
      </Suspense>
    );
  }
  return DynamicComponent;
}
