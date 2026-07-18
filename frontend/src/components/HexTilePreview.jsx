import { buildApiUrl } from "../utils/connection.js";

export const effectIcons = {
  gain_energy: "E+",
  gain_neurons: "N+",
  gain_seashells: "S+",
  place_shelter_token: "SH",
  lose_energy: "E-",
  lose_neurons: "N-",
  lose_seashells: "S-",
  lose_ap: "AP-",
  lose_half_ap: "AP/2",
  lose_all_ap: "AP0",
  pulpita_move_previous: "P<-",
  pulpita_move_free: "MOVE",
  keep_tile: "KEEP",
  remove_tile: "OUT",
  move_tile_previous: "T<-",
  remove_preys: "CAT",
};

const itemSizeClass = (count) => {
  if (count > 8) return "h-5 min-w-5 text-[0.45rem]";
  if (count > 5) return "h-6 min-w-6 text-[0.5rem]";
  return "h-7 min-w-7 text-[0.58rem]";
};

const InteractionIcon = ({ interaction, counter }) => {
  const iconUrl = interaction?.image_url ? buildApiUrl(interaction.image_url) : "";
  return (
    <span className={`${counter ? "rounded-sm border-fuchsia-500 bg-fuchsia-50" : "rounded-full border-teal-500 bg-white"} flex h-7 w-7 items-center justify-center overflow-hidden border text-[0.55rem] font-bold text-teal-900 shadow-sm`}>
      {iconUrl ? <img alt="" className="h-full w-full object-cover" src={iconUrl} /> : interaction?.name?.slice(0, 2) || "?"}
    </span>
  );
};

const EffectIcon = ({ effect, total }) => (
  <span className={`${itemSizeClass(total)} inline-flex items-center justify-center rounded-full border border-cyan-200 bg-white px-1 font-bold text-teal-900 shadow-sm`} title={effect.type}>
    {effectIcons[effect.type] || "?"}
    {effect.category_id ? <small className="ml-0.5 font-semibold">{String(effect.category_id).slice(0, 2)}</small> : null}
    {effect.amount ? <small className="ml-0.5 font-semibold">{effect.amount}</small> : null}
  </span>
);

const EffectZone = ({ effects = [], className = "" }) => (
  <div className={`flex flex-wrap items-center justify-center gap-1 ${className}`}>
    {effects.map((effect, index) => <EffectIcon effect={effect} key={`${effect.type}:${index}`} total={effects.length} />)}
  </div>
);

const CostZone = ({ ids = [], interactionsById, counter = false }) => (
  <div className="flex flex-wrap items-center justify-center gap-1">
    {ids.map((id) => <InteractionIcon counter={counter} interaction={interactionsById[id]} key={id} />)}
  </div>
);

const ShellRequirementZone = ({ count = 0 }) => {
  const total = Math.max(0, Number(count || 0));
  if (!total) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-1">
      {Array.from({ length: total }).map((_, index) => (
        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-amber-300 bg-amber-50 text-[0.55rem] font-bold text-amber-900 shadow-sm" key={index} title="Poulpita shell required">
          S
        </span>
      ))}
    </div>
  );
};

const HexTilePreview = ({ tile, event, interactionsById = {}, className = "" }) => {
  const imageUrl = event?.image_url ? buildApiUrl(event.image_url) : "";
  return (
    <div className={`relative mx-auto aspect-[1.05/1] w-full max-w-[18rem] ${className}`}>
      <div
        className="absolute inset-0 border border-teal-300 bg-cyan-50 shadow-md"
        style={{ clipPath: "polygon(25% 4%, 75% 4%, 100% 50%, 75% 96%, 25% 96%, 0 50%)" }}
      />
      <div className="absolute left-[16%] right-[16%] top-[16%] aspect-square overflow-hidden rounded-full border border-cyan-200 bg-white shadow-sm">
        {imageUrl ? <img alt={event?.name || "Tile"} className="h-full w-full object-cover" src={imageUrl} /> : null}
      </div>
      <div className="absolute left-[18%] right-[18%] top-[6%] flex flex-col items-center gap-1">
        <CostZone ids={tile?.interaction_ids || []} interactionsById={interactionsById} />
        <ShellRequirementZone count={tile?.shell_requirement_count || 0} />
        {(tile?.counter_attack_interaction_ids || []).length ? <CostZone counter ids={tile.counter_attack_interaction_ids} interactionsById={interactionsById} /> : null}
      </div>
      <EffectZone className="absolute bottom-[31%] left-[4%] top-[31%] w-[22%]" effects={tile?.success_effects || []} />
      <EffectZone className="absolute bottom-[31%] right-[4%] top-[31%] w-[22%]" effects={tile?.counter_attack_effects || []} />
      <EffectZone className="absolute bottom-[6%] left-[20%] right-[20%] min-h-[20%]" effects={tile?.failure_effects || []} />
    </div>
  );
};

export default HexTilePreview;
