import { buildApiUrl } from "../utils/connection.js";

const CardPreview = ({ card, categories = [], className = "" }) => (
  <article className={`rounded-md border border-cyan-200 bg-white p-3 text-slate-700 shadow-sm ${className}`}>
    <div className="flex items-center gap-3">
      {card?.image_url ? <img alt="" className="h-12 w-12 rounded object-cover" src={buildApiUrl(card.image_url)} /> : null}
      <h3 className="font-semibold text-teal-950">{card?.name || "Card"}</h3>
    </div>
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {categories.map((category) => {
        const resolved = card?.resolves?.[category.id] || [];
        return (
          <div className={`rounded border p-2 ${category.special ? "border-fuchsia-200 bg-fuchsia-50" : "border-cyan-100 bg-cyan-50"}`} key={category.id}>
            <p className="text-xs font-semibold text-teal-900">{category.name}</p>
            {resolved.length ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {resolved.map((entry) => (
                  <span className="inline-flex items-center gap-1 rounded bg-white px-2 py-1 text-xs text-slate-700 shadow-sm" key={`${entry.tile_id}:${entry.event_id}:${entry.requirement_type}`}>
                    {entry.event_image_url ? <img alt="" className="h-5 w-5 rounded object-cover" src={buildApiUrl(entry.event_image_url)} /> : null}
                    {entry.event_name}
                  </span>
                ))}
              </div>
            ) : <p className="mt-2 text-xs text-slate-400">None</p>}
          </div>
        );
      })}
    </div>
  </article>
);

export default CardPreview;
