import { randomTopic } from '../data/topicLibrary.js'

function difficultyClass(value) {
  return `difficulty-${String(value || '').toLowerCase()}`
}

export default function TopicLibraryPicker({ selectedId, topics = [], onSelect, onCustom, onRefresh, refreshing = false, refreshError = '' }) {
  return (
    <section className="topic-library-block">
      <div className="topic-library-heading">
        <div>
          <div className="eyebrow">Topic library</div>
          <h3>Choose a topic</h3>
          <p>Select a topic or refresh for new ideas.</p>
        </div>
        <div className="topic-library-actions">
          <button type="button" className="ghost-button refresh-topic-button" disabled={refreshing} onClick={onRefresh}>
            <span className={refreshing ? 'refresh-spin' : ''}>↻</span> {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
          <button type="button" className="ghost-button" disabled={!topics.length || refreshing} onClick={() => onSelect(randomTopic(topics))}>Surprise me</button>
          <button type="button" className={`ghost-button ${selectedId === 'custom' ? 'selected' : ''}`} onClick={onCustom}>Custom topic</button>
        </div>
      </div>
      {refreshError && <div className="topic-refresh-error">{refreshError}</div>}
      <div className={`topic-library-grid ${refreshing ? 'refreshing' : ''}`}>
        {topics.map((topic) => (
          <button
            type="button"
            key={topic.id}
            className={`topic-library-card ${selectedId === topic.id ? 'selected' : ''}`}
            onClick={() => onSelect(topic)}
            disabled={refreshing}
          >
            <div className="topic-library-card-top">
              <span className={`topic-difficulty ${difficultyClass(topic.difficulty)}`}>{topic.difficulty}</span>
              <span className="topic-domain">{topic.domain}</span>
            </div>
            <strong>{topic.title}</strong>
            <small>{topic.recommendedAudience}</small>
          </button>
        ))}
      </div>
    </section>
  )
}
