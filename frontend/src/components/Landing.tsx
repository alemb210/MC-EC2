type LandingProps = { onEnter: () => void; signedIn?: boolean; accountEmail?: string; onLogout?: () => void };

const questions = [
  ["Will our world still be there next time?", "Yes. Stopping your server keeps its world for the next session. Deleting the server permanently removes it and its world. Backups are not currently available."],
  ["Does the server start when someone joins?", "Someone needs to log in and start it first. Startup takes a few minutes; wait until the dashboard says Minecraft is ready before joining."],
  ["What if we forget to stop it?", "Idle shutdown stops an empty server after a period of time. Your world stays between sessions."],
  ["Can my friends start the server too?", "Yes. The owner can add friends with confirmed MCWorldControl accounts as admins. They can start and stop the server and manage player access."],
  ["How do we choose who can join?", "Choose public access or an allowlist of Minecraft usernames. Player access does not give anyone server-control permissions."],
];

function PreviewCard({ name, ready, onEnter }: { name: string; ready: boolean; onEnter: () => void }) {
  return <article className="preview-server">
    <div className="preview-scenery" aria-hidden="true"><span className="scene-hill" /><span className="scene-tree" /></div>
    <div className="preview-server-body">
      <div className="preview-server-title"><h4>{name}</h4><span className={`state ${ready ? "running" : "stopped"}`}>{ready ? "Ready to join" : "Stopped"}</span></div>
      <p>{ready ? "2 / 20 players online" : "World saved for next time"}</p>
      <div className="preview-address">{ready ? "203.0.113.42:25565" : "Address available when running"}</div>
      <button className={ready ? "secondary" : ""} onClick={onEnter}>{ready ? "Open dashboard" : "Start in dashboard"}</button>
    </div>
  </article>;
}

export default function Landing({ onEnter, signedIn = false, accountEmail, onLogout }: LandingProps) {
  const entry = signedIn ? "Open dashboard" : "Log in";
  return <div className={`landing ${signedIn ? "signed-in" : ""}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header container"><a className="brand" href="#main-content" aria-label="MCWorldControl home"><span className="brand-mark" aria-hidden="true">▰</span>MC<span>WorldControl</span></a><nav aria-label="Main navigation"><a href="#how-it-works">How it works</a><a href="#faq">FAQ</a><button onClick={onEnter}>{entry} <span aria-hidden="true">↗</span></button>{signedIn && onLogout && <details className="account-menu"><summary>Account</summary><div><span>{accountEmail}</span><button className="secondary" onClick={onLogout}>Log out</button></div></details>}</nav></header>
    <main id="main-content" className="container">
      <section className="hero"><div className="hero-copy"><p className="eyebrow">FOR THE OCCASIONAL ADVENTURERS</p><h1>Your world.<br />On your<br /><em>schedule.</em></h1><p className="hero-description">A Minecraft server for when the group chat finally says, “tonight?” Start it when you play. Keep your world between sessions. Let idle shutdown handle the rest.</p><div className="hero-actions"><button onClick={onEnter}>{entry} <span aria-hidden="true">→</span></button><a href="#how-it-works">See how it works →</a></div><p className="hero-note">◷ &nbsp; Start a few minutes before game night.</p></div><div className="hero-art"><div className="island-scene" role="img" aria-label="A small Minecraft inspired world waiting for game night"><div className="moon" /><div className="island"><div className="island-top"><span className="cabin" /><span className="pine one" /><span className="pine two" /><span className="pine three" /></div><div className="island-earth" /></div></div><div className="hero-server"><strong>Sunday survival</strong><span className="state stopped">Stopped</span><p>World saved. Pick up where you left off.</p><button onClick={onEnter}>Start in dashboard →</button></div></div></section>
      <div className="principles"><span>◷ &nbsp; Stops when nobody's playing</span><span>▣ &nbsp; Your world stays between sessions</span><span>♧ &nbsp; Share control with friends</span><span>◇ &nbsp; Choose who can join</span></div>
      <section className="landing-section" aria-labelledby="preview-title"><div className="section-head"><div><p className="eyebrow">LESS SETUP. MORE PLAYING.</p><h2 id="preview-title">Game night starts here.</h2></div><p>Your servers, their status, and the address your friends need. All in one quiet little dashboard.</p></div><div className="dashboard-preview"><div className="preview-chrome"><span aria-hidden="true">● ● ●</span> MCWorldControl / YOUR SERVERS <span>PRODUCT PREVIEW</span></div><div className="preview-content"><h3>Your servers</h3><p>A home for every adventure.</p><div className="preview-grid"><PreviewCard name="Sunday survival" ready={false} onEnter={onEnter} /><PreviewCard name="The long weekend" ready onEnter={onEnter} /></div><button className="link" onClick={onEnter}>{signedIn ? "Open your servers" : "Log in to your servers"} →</button></div></div></section>
      <section id="how-it-works" className="landing-section steps-section" aria-labelledby="steps-title"><div className="section-head"><div><p className="eyebrow">FITS AROUND REAL LIFE</p><h2 id="steps-title">Whenever everyone’s free.</h2></div><p>A weekend, a spare evening, or the occasional spontaneous session.</p></div><div className="steps-grid"><div><span>01 / GET READY</span><h3>Start your server.</h3><p>Log in and hit Start. Give Minecraft a few minutes to get ready while you round up your friends.</p></div><div><span>02 / GET TOGETHER</span><h3>Pick up your adventure.</h3><p>Copy the current address into Minecraft and carry on with your shared world.</p></div><div><span>03 / CALL IT A NIGHT</span><h3>Leave the world waiting.</h3><p>Stop the server when you're done. Forget? Idle shutdown stops it after everyone has left. Your world stays.</p></div></div><div className="benefits"><div><h3>Made for the in-between.</h3><p>Play every Sunday or skip a month. Your server can rest between sessions.</p></div><div><h3>Pass around the controls.</h3><p>Add a trusted friend as an admin so they can start the server when you're away.</p></div><div><h3>Your kind of company.</h3><p>Keep an allowlist of Minecraft usernames or open the server to anyone with the address.</p></div></div></section>
      <section id="faq" className="landing-section faq-section" aria-labelledby="faq-title"><div><p className="eyebrow">BEFORE YOU HOP IN</p><h2 id="faq-title">A few good questions.</h2></div><div className="faq-list">{questions.map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div></section>
      <section className="closing"><div><h2>Same world. Next adventure.</h2><p>We'll be here when the group chat gets going.</p></div><button onClick={onEnter}>{entry} →</button></section>
    </main><footer className="container site-footer">MCWorldControl <span>Your world. On your schedule.</span></footer>
  </div>;
}
