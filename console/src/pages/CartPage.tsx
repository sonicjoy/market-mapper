import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { submitBatch, verifyBatch } from "../api";
import { LiveAckCheckbox } from "../components/LiveAckCheckbox";
import { PageHeader } from "../components/PageHeader";
import { RulePreviewCards, type RuleCard } from "../components/RulePreviewCards";
import {
  cartToBatchBody,
  clearCart,
  getCartItems,
  removeCartItem,
  replaceCart,
  useCart,
  type CartItem,
} from "../cartStore";
import { aliasCartLines, leagueCartLines } from "../lib/cartDetails";
import { cartItemToEntryState } from "../lib/cartEntryState";
import { GATEWAY_DROP_NOTE, isGatewayDrop } from "../lib/gatewayDrop";
import { cartMarketRuleLines, formatMarketRuleCartLabel, pinsFromPayload } from "../lib/marketRules";
import type { ReviewCard } from "../types";

function kindLabel(kind: CartItem["kind"]): string {
  switch (kind) {
    case "entity_alias":
      return "Alias";
    case "mapping_league":
      return "League";
    case "mapping_market_rules":
      return "Market rule";
    default: {
      const _exhaustive: never = kind;
      return _exhaustive;
    }
  }
}

function CartDetailList({ headline, lines }: { headline: string; lines: string[] }) {
  if (!lines.length) {
    return <div className="text-sm text-slate-800 dark:text-slate-100">{headline}</div>;
  }
  return (
    <div>
      <div className="text-sm text-slate-800 dark:text-slate-100">{headline}</div>
      <ul className="mt-1 space-y-0.5 font-mono text-xs text-slate-600 dark:text-slate-300">
        {lines.map((line, i) => (
          <li key={`${line}-${i}`}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

function MarketRuleCartBody({ item }: { item: CartItem }) {
  const league = String(item.payload.league ?? "").trim();
  const pins = pinsFromPayload(item.payload);
  const lines = cartMarketRuleLines(item.payload);
  const headline = lines.length
    ? formatMarketRuleCartLabel(league, pins)
    : item.label;
  return <CartDetailList headline={headline} lines={lines.length > 1 ? lines : []} />;
}

function CartItemBody({ item }: { item: CartItem }) {
  switch (item.kind) {
    case "mapping_market_rules":
      return <MarketRuleCartBody item={item} />;
    case "mapping_league":
      return <CartDetailList headline={item.label} lines={leagueCartLines(item.payload)} />;
    case "entity_alias":
      return <CartDetailList headline={item.label} lines={aliasCartLines(item.payload)} />;
    default: {
      const _exhaustive: never = item.kind;
      return <div className="text-sm text-slate-800 dark:text-slate-100">{_exhaustive}</div>;
    }
  }
}

export function CartPage() {
  const cart = useCart();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [ackShadow, setAckShadow] = useState(false);
  const [note, setNote] = useState("");
  const [previewToken, setPreviewToken] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<string[]>([]);
  const [cards, setCards] = useState<RuleCard[]>([]);
  const [submittedRef, setSubmittedRef] = useState<string | null>(null);
  const [submitNote, setSubmitNote] = useState<string | null>(null);

  const cartFingerprint = cart.map((i) => i.id).join(",");
  useEffect(() => {
    setPreviewToken(null);
    setSummary(null);
    setEvidence([]);
    setCards([]);
    setBlockers([]);
    setWarnings([]);
  }, [cartFingerprint]);

  const verify = useMutation({
    mutationFn: () => {
      const body = cartToBatchBody(cart);
      return verifyBatch({
        ...body,
        note: note || undefined,
        acknowledge_shadow: ackShadow,
      });
    },
    onSuccess: (res) => {
      setBlockers(res.blockers ?? []);
      setWarnings(res.warnings ?? []);
      setSummary(res.preview?.summary ?? null);
      setEvidence(res.preview?.evidence ?? []);
      setCards(res.preview?.cards ?? []);
      setPreviewToken(res.ok && res.preview_token ? res.preview_token : null);
    },
  });

  const submit = useMutation({
    mutationFn: () => {
      if (!previewToken) throw new Error("missing preview");
      return submitBatch(previewToken);
    },
    onMutate: () => {
      const snapshot = getCartItems();
      clearCart();
      setSubmitNote(null);
      return { snapshot };
    },
    onSuccess: (card: ReviewCard) => {
      setSubmittedRef(card.ref);
      setPreviewToken(null);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err, _vars, ctx) => {
      void qc.invalidateQueries({ queryKey: ["review"] });
      if (isGatewayDrop(err)) {
        setPreviewToken(null);
        setSubmitNote(GATEWAY_DROP_NOTE);
        return;
      }
      if (ctx?.snapshot.length) replaceCart(ctx.snapshot);
    },
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Staging cart"
        description="Accumulate alias, league, and market-rule changes, then submit one compound proposal (one rule-set snapshot)."
      />

      {cart.length === 0 && !submittedRef && !submit.isPending && !submitNote ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Cart is empty. Verify a change on{" "}
          <Link className="text-brand-700 underline dark:text-brand-300" to="/entry">
            Editor
          </Link>{" "}
          and choose Add to cart.
        </p>
      ) : null}
      {submit.isPending ? <p className="text-sm text-slate-600 dark:text-slate-300">Submitting for review…</p> : null}

      {cart.length > 0 ? (
        <div className="card space-y-3">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {cart.map((item) => (
              <li key={item.id} className="flex items-start justify-between gap-3 py-2">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {kindLabel(item.kind)}
                  </div>
                  <CartItemBody item={item} />
                </div>
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    className="text-xs text-brand-700 hover:underline dark:text-brand-300"
                    onClick={() => navigate("/entry", { state: cartItemToEntryState(item) })}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="text-xs text-red-700 hover:underline"
                    onClick={() => {
                      removeCartItem(item.id);
                      setPreviewToken(null);
                    }}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <div>
            <label className="label" htmlFor="cart-note">
              Note (optional)
            </label>
            <input
              id="cart-note"
              className="input"
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setPreviewToken(null);
              }}
            />
          </div>

          <LiveAckCheckbox
            batch
            checked={ackShadow}
            onChange={(checked) => {
              setAckShadow(checked);
              setPreviewToken(null);
            }}
          />

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={verify.isPending || submit.isPending}
              onClick={() => verify.mutate()}
            >
              Verify batch
            </button>
            {previewToken ? (
              <button
                type="button"
                className="btn-primary"
                disabled={submit.isPending}
                onClick={() => submit.mutate()}
              >
                Submit for review
              </button>
            ) : null}
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                clearCart();
                setPreviewToken(null);
              }}
            >
              Clear cart
            </button>
          </div>

          {blockers.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-red-700">
              {blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : null}
          {warnings.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-200">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {summary ? (
            <div className="notice-brand text-sm">
              <div className="font-medium">Batch preview</div>
              <p className="mt-1">{summary}</p>
              <RulePreviewCards cards={cards} />
              {evidence.length ? (
                <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs">
                  {evidence.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {(verify.error || submit.error) && (
            <p className="text-sm text-red-600">
              {(verify.error || submit.error)?.message}
            </p>
          )}
        </div>
      ) : null}

      {submitNote ? (
        <p className="text-sm text-amber-800 dark:text-amber-200">
          {submitNote}{" "}
          <Link className="underline" to="/review">
            Open Review
          </Link>
        </p>
      ) : null}
      {submittedRef ? (
        <p className="text-sm text-slate-700 dark:text-slate-300">
          Batch submitted - waiting for checker.{" "}
          <Link className="text-brand-700 underline dark:text-brand-300" to={`/review/${submittedRef}`}>
            Open review
          </Link>
          {" · "}
          <button
            type="button"
            className="text-brand-700 underline dark:text-brand-300"
            onClick={() => navigate("/entry")}
          >
            Back to entry
          </button>
        </p>
      ) : null}
    </div>
  );
}
