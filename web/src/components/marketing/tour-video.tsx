"use client";

import { useState } from "react";
import { Play } from "lucide-react";

/**
 * The 90-second platform tour. Nothing downloads until the visitor presses
 * play: the poster is the only request on page load. The voice is generated,
 * and the caption says so.
 */
export function TourVideo() {
  const [playing, setPlaying] = useState(false);
  return (
    <div className="lp-tour">
      <div className="lp-tour-frame">
        {playing ? (
          <video
            className="lp-tour-video"
            src="/video/apex4traders-tour.mp4"
            poster="/video/tour-poster.webp"
            controls
            autoPlay
            playsInline
            preload="none"
          />
        ) : (
          <button
            type="button"
            className="lp-tour-play"
            onClick={() => setPlaying(true)}
            aria-label="Play the 90-second platform tour"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/video/tour-poster.webp" alt="" width={1280} height={720} />
            <span className="lp-tour-btn"><Play size={22} aria-hidden /> Watch the tour, 1 min 38 s</span>
          </button>
        )}
      </div>
      <p className="lp-tour-note">
        Demo account shown. Narrated by an AI-generated voice. Not financial
        advice. Leveraged trading carries a high risk of loss.
      </p>
    </div>
  );
}
