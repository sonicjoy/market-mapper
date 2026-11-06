import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import "swagger-ui-react/swagger-ui.css";

import { PageHeader } from "../components/PageHeader";

const SwaggerUI = lazy(() => import("swagger-ui-react"));

async function fetchOpenApi(): Promise<object> {
  const res = await fetch("/api/openapi.json", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<object>;
}

export function ApiDocsPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["openapi"],
    queryFn: fetchOpenApi,
  });

  return (
    <div>
      <PageHeader
        title="API Docs"
        description={
          <>
            Live OpenAPI for the mapping control plane. Written guide:{" "}
            <code className="text-[11px]">docs/mapping-rules/control-plane-api.md</code>
          </>
        }
      />
      {isLoading && <p className="text-sm text-slate-500 dark:text-slate-400">Loading OpenAPI…</p>}
      {isError && (
        <p className="text-sm text-red-600">
          Could not load OpenAPI: {(error as Error).message}. Is the API on :8000?
        </p>
      )}
      {data && (
        <div
          className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-700"
          style={{ colorScheme: "light" }}
        >
          <Suspense fallback={<p className="p-4 text-sm text-slate-500 dark:text-slate-400">Loading Swagger…</p>}>
            <SwaggerUI
              spec={data}
              tryItOutEnabled
              docExpansion="list"
              supportedSubmitMethods={["get", "post", "put", "delete", "patch"]}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}

export default ApiDocsPage;
