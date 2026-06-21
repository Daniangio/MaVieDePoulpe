import { buildApiUrl } from "../utils/connection.js";

const imageUrl = (entry) => (entry?.image_url ? buildApiUrl(entry.image_url) : "");

const PlayerBoardPreview = ({ board, eventsById = {}, interactionsById = {}, className = "" }) => {
  const defaultHandSize = Math.max(1, Number(board?.default_max_cards_in_hand || 3));
  const upgradeSlots = (board?.hand_size_upgrades || []).reduce((total, upgrade) => total + Math.max(1, Number(upgrade.hand_size_bonus || 1)), 0);
  const totalHandSlots = defaultHandSize + upgradeSlots;
  const initiatedEvents = (board?.initiates_event_ids || []).map((eventId) => eventsById[eventId]).filter(Boolean);
  const deckEntries = (board?.deck || []).filter((entry) => Number(entry.count || 0) > 0);

  return (
    <article className={`overflow-hidden rounded-lg border border-cyan-200 bg-white shadow-sm ${className}`}>
      <div className="border-b border-cyan-100 bg-gradient-to-r from-cyan-100 to-teal-50 px-4 py-3">
        <h3 className="truncate text-lg font-semibold text-teal-950">{board?.name || "Player board"}</h3>
      </div>

      <div className="grid gap-3 p-3">
        <PreviewBox title="Interactions">
          <div className="flex flex-wrap gap-2">
            {initiatedEvents.map((event) => (
              <span className="inline-flex items-center gap-2 rounded-md border border-cyan-100 bg-cyan-50 px-2 py-1 text-xs text-teal-950" key={event.id} title={event.name}>
                {imageUrl(event) ? <img alt="" className="h-7 w-7 rounded object-cover" src={imageUrl(event)} /> : null}
                <span className="max-w-[7rem] truncate">{event.name}</span>
              </span>
            ))}
            {initiatedEvents.length === 0 ? <p className="text-xs text-slate-400">No events selected.</p> : null}
          </div>
        </PreviewBox>

        <PreviewBox title="Cards">
          <div className="grid gap-2">
            {deckEntries.map((entry) => {
              const interaction = interactionsById[entry.interaction_id];
              return (
                <div className="grid grid-cols-[2rem_1fr_auto] items-center gap-2 rounded-md bg-cyan-50/80 px-2 py-1.5 text-sm" key={entry.interaction_id}>
                  {imageUrl(interaction) ? <img alt="" className="h-8 w-8 rounded object-cover" src={imageUrl(interaction)} /> : <span className="h-8 w-8 rounded bg-cyan-100" />}
                  <span className="min-w-0 truncate text-slate-700">{interaction?.name || entry.interaction_id}</span>
                  <span className="rounded-full bg-teal-500 px-2 py-0.5 text-xs font-semibold text-white">x{entry.count}</span>
                </div>
              );
            })}
            {deckEntries.length === 0 ? <p className="text-xs text-slate-400">No cards in deck.</p> : null}
          </div>
        </PreviewBox>

        <div className="grid gap-3 sm:grid-cols-2">
          <PreviewBox title="Hand">
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: totalHandSlots }).map((_slot, index) => (
                <span
                  aria-label={index < defaultHandSize ? "Available by default" : "Upgrade slot"}
                  className={`h-4 w-4 rounded-full border ${index < defaultHandSize ? "border-teal-500 bg-teal-400" : "border-cyan-300 bg-white"}`}
                  key={index}
                />
              ))}
            </div>
          </PreviewBox>

          <PreviewBox title="Control">
            <div className="grid grid-cols-2 gap-2 text-center text-xs">
              <div className="rounded-md bg-cyan-50 p-2">
                <p className="text-slate-500">Per night</p>
                <p className="text-lg font-semibold text-teal-950">{board?.control_takes_per_night || 3}</p>
              </div>
              <div className="rounded-md bg-cyan-50 p-2">
                <p className="text-slate-500">Actions</p>
                <p className="text-lg font-semibold text-teal-950">{board?.actions_per_control || 3}</p>
              </div>
            </div>
          </PreviewBox>
        </div>
      </div>
    </article>
  );
};

const PreviewBox = ({ title, children }) => (
  <section className="rounded-md border border-cyan-100 bg-white p-3">
    <h4 className="mb-2 text-xs font-semibold uppercase text-teal-900">{title}</h4>
    {children}
  </section>
);

export default PlayerBoardPreview;
