export default function PlaceholderModule({ eyebrow, title, description, icon, pill = 'Reserved', ready = false }) {
  return (
    <div className={`placeholder-module ${ready ? 'ready' : ''}`}>
      <div className="placeholder-icon">{icon}</div>
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <span className={`reserved-pill ${ready ? 'ready-pill' : ''}`}>{pill}</span>
    </div>
  )
}
