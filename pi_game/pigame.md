# Alphabet Learning Module
## Technical Design & Execution Plan
### Project: Wini Educational Robot
### Platform: Raspberry Pi 5 + 7" Waveshare DSI Touch Display
### Version: 1.0

---

# 1. Objective

The objective of this module is **not** to build another educational game.

The objective is to build a **calm, conversational, physically embodied learning experience** that introduces children to the English alphabet.

The robot should feel like a learning companion rather than an application.

Children should never feel they are being tested.

Instead, they should feel that they are helping the robot learn.

Every interaction must reinforce curiosity instead of excitement.

---

# 2. Design Philosophy

This module follows five core principles.

## 2.1 Calm Computing

The interface should never attempt to maximize engagement through dopamine-driven mechanics.

Therefore the system will NOT include:

- Coins
- Rewards
- Daily streaks
- Timers
- Flashing animations
- Fireworks
- Confetti
- XP
- Leaderboards
- Lives
- Penalties
- Pop-up achievements
- Random rewards

The child should enjoy the learning process itself.

---

## 2.2 One Goal Per Screen

Every screen must communicate exactly one task.

Examples:

✔ Touch the letter

✔ Listen

✔ Repeat

✔ Find

✔ Drag

Never show multiple tasks simultaneously.

---

## 2.3 Embodied Learning

Unlike tablets, our robot possesses voice and personality.

Every interaction should be framed as helping the robot.

Instead of

"Correct!"

The robot says

"Thank you! I found it."

Instead of

"Wrong"

The robot says

"Let's try together."

The robot should never judge.

---

## 2.4 Slow Interaction

Animations should be slow.

Speech should pause naturally.

The child must have time to think.

Never rush interaction.

---

## 2.5 Consistency

Every alphabet lesson follows the exact same structure.

Children learn routines.

Consistency lowers cognitive load.

---

# 3. Hardware Platform

## Compute

Raspberry Pi 5

---

## Display

Waveshare 7" DSI Capacitive Touch

Resolution

600 × 1024

Portrait Orientation

---

## Audio

ReSpeaker microphone

Speaker output

---

## Input

Touch

Voice

No keyboard

No mouse

---

# 4. Software Stack

The complete application will be developed using Flutter.

## Why Flutter

Flutter provides

- Smooth rendering
- Excellent touch support
- High performance on Raspberry Pi 5
- Offline asset management
- Strong animation framework
- Simple state management
- Future portability to Android if required

No Qt.

No Electron.

No WebView.

Flutter is the only UI framework.

---

# 5. Overall Architecture

```
                    Flutter Application
                           │
         ┌────────────────────────────────┐
         │         Navigation Layer        │
         └────────────────────────────────┘
                           │
         ┌────────────────────────────────┐
         │      Lesson State Machine       │
         └────────────────────────────────┘
                           │
      ┌──────────────┬───────────────┬─────────────┐
      │              │               │             │
 Content Loader   Audio Manager   Voice Manager   Animation
      │              │               │             │
      └──────────────┴───────────────┴─────────────┘
                           │
                    Robot Expression API
```

Every lesson is data-driven.

No lesson logic should be hardcoded.

---

# 6. Folder Structure

```
alphabet_module/

assets/

    letters/

        A/

            lesson.json

            apple.png

            ant.png

            intro.wav

            phonics.wav

            trace.svg

            story.wav

        B/

        C/

games/

    trace/

    identify/

    drag/

audio/

fonts/

animations/

lib/

    models/

    screens/

    widgets/

    managers/

    lesson/

    voice/

    animation/

    audio/

```

---

# 7. Lesson Structure

Every alphabet follows identical stages.

There are no exceptions.

```
Introduction

↓

Hear Letter

↓

Touch Letter

↓

Repeat Sound

↓

Find Letter

↓

Object Association

↓

Mini Activity

↓

Completion

↓

Next Letter
```

---

# 8. Lesson Stage Details

---

## Stage 1

### Robot Introduction

Robot speaks

"Hello.
Today we're meeting the letter A."

Display

Large letter

Nothing else.

Implementation

Load

- Letter SVG
- Intro audio

Animation

Letter slowly appears.

Duration

3 seconds

---

## Stage 2

### Listen

Robot

"A says Ah."

Play phoneme.

Display

Large letter only.

No buttons.

Child simply listens.

---

## Stage 3

### Touch

Robot

"Can you touch A?"

Display

Four letters

A

B

C

D

Child taps A.

Correct

Letter enlarges.

Robot

"Thank you!"

Wrong

Robot

"Let's look again."

No buzzer.

No red color.

---

## Stage 4

### Repeat

Robot

"Can you say Ah?"

Microphone records.

Whisper performs speech recognition.

Expected phoneme

ah

Simple phoneme confidence threshold

>= 0.70

Correct

Robot smiles.

Wrong

Robot repeats once.

Maximum attempts

2

If still incorrect

Robot continues.

No failure state.

---

## Stage 5

### Object Association

Robot

"Apple begins with A."

Display

Apple image.

Nothing else.

Pause.

No quiz.

---

## Stage 6

### Mini Activity

Only one activity.

Never multiple games.

Current activity

Feed Apple

Apple appears.

Robot opens mouth.

Child drags apple.

Robot eats.

Robot

"Yummy!"

Duration

10 seconds

---

## Stage 7

### Completion

Robot

"We learned A today."

Large A

Small apple

Next button

---

# 9. UI Design Specification

Target Resolution

600 × 1024

Portrait

---

## Screen Layout

```
--------------------------------

Robot Status

-------------------------------

Main Content Area

-------------------------------

Instruction

-------------------------------

Action Button

--------------------------------
```

---

## Touch Targets

Minimum

72 px

Spacing

24 px

Rounded corners

20 px radius

---

## Typography

Primary Font

Nunito

Letter Size

180 px

Instruction

34 px

Buttons

32 px

---

## Color Palette

Background

Warm White

#F8F5EF

Primary

Soft Blue

Accent

Pastel Green

Highlight

Muted Orange

Avoid

Pure Red

Pure Green

Neon

---

# 10. Animation Principles

Maximum animation duration

600 ms

Animation curves

Ease In Out

Only

Scale

Fade

Slide

No

Bounce

Shake

Explosion

Flash

Spin

---

# 11. Audio Design

Speech

Piper TTS

Voice

Warm

Slow

Friendly

---

Effects

Paper

Wood

Bell

Soft Click

Bird Chirp

No arcade sounds.

No applause.

---

# 12. State Machine

```
Idle

↓

Load Lesson

↓

Robot Intro

↓

Listen

↓

Touch

↓

Repeat

↓

Association

↓

Mini Activity

↓

Completed

↓

Next Lesson
```

State transitions are deterministic.

No random branching.

---

# 13. Voice Pipeline

```
Wake Word

↓

Whisper Streaming

↓

Speech Recognition

↓

Intent

↓

Lesson Validator

↓

Robot Response

↓

Piper TTS

↓

Animation
```

No cloud processing.

Everything offline.

---

# 14. Lesson Data Format

```
{
    "letter": "A",

    "phoneme": "ah",

    "objects":
    [
        {
            "name":"Apple",
            "image":"apple.png"
        }
    ],

    "mini_game":"feed",

    "story":"story.wav"
}
```

Lessons contain data only.

Never executable logic.

---

# 15. Progress Tracking

Each letter stores

```
attempts

completed

touch_accuracy

speech_attempts

date_completed
```

No scores.

No grades.

No ranking.

---

# 16. Parent Dashboard Data

Store

```
Letters Completed

Practice Time

Days Practiced

Speech Attempts

Touch Attempts

Confidence Trend
```

Never expose scores to the child.

Only parents see analytics.

---

# 17. Performance Budget

Target

60 FPS

Frame time

<16 ms

App startup

<2 seconds

Lesson loading

<300 ms

Touch latency

<30 ms

Audio latency

<80 ms

Memory

<500 MB

CPU

<35%

GPU

<30%

---

# 18. Phase-wise Development Plan

---

## Phase 1

Application Framework

Implement

- Flutter project
- Portrait layout
- Theme
- Navigation
- Asset loading
- State management

Do NOT implement

- Games
- Voice
- Analytics

Deliverable

Running application shell.

---

## Phase 2

Lesson Engine

Implement

- Lesson JSON parser
- Lesson state machine
- Navigation
- Asset preloading

Deliverable

Letter lessons work using static assets.

---

## Phase 3

Core UI

Implement

- Introduction screen
- Touch screen
- Association screen
- Completion screen

Deliverable

Entire lesson works using touch only.

---

## Phase 4

Mini Activity

Implement

Feed Apple interaction.

No additional games.

Deliverable

One polished activity.

---

## Phase 5

Voice

Implement

- Whisper
- Piper
- Voice prompts
- Speech validation

Deliverable

Offline speaking lesson.

---

## Phase 6

Robot Integration

Implement

Robot expressions

LED

Ear movement

Head movement

Body animation

Robot responds during lessons.

---

## Phase 7

Progress

Implement

SQLite

Lesson completion

Resume

Parent analytics

Deliverable

Persistent learning records.

---

## Phase 8

Content Expansion

Create

26 alphabet lessons

using identical structure.

No new interaction types.

Only content changes.

---

# 19. Explicit Non-Goals

The following are intentionally excluded from Version 1.0:

- Alphabet songs
- Animated cartoons
- Story branching
- AI-generated lesson content
- Multiplayer activities
- Internet connectivity
- Video playback
- Adaptive difficulty
- Randomized rewards
- Mini-game selection
- Badge systems
- Achievement systems
- Character customization
- Daily challenges
- Learning streaks
- Time-limited tasks
- Competitive mechanics
- Social sharing
- Cloud synchronization

These features increase implementation complexity or encourage extrinsic motivation. Version 1.0 focuses on a calm, consistent, and technically robust learning experience.

---

# 20. Definition of Done

The Alphabet Learning Module is considered complete when all of the following criteria are satisfied:

1. The application runs entirely offline on the Raspberry Pi 5.
2. The interface is optimized for the 600 × 1024 portrait touchscreen.
3. All 26 alphabet lessons follow the exact same interaction sequence.
4. Every lesson includes:
   - Introduction
   - Phoneme playback
   - Letter identification
   - Speech repetition
   - Object association
   - Feed Apple mini activity (adapted to the corresponding letter)
   - Completion screen
5. Voice recognition and text-to-speech operate locally without cloud services.
6. Robot expressions remain synchronized with lesson progression.
7. Lesson assets are loaded from local storage with no perceptible delay.
8. Progress is stored locally in SQLite and exposed only through the parent dashboard.
9. The application maintains 60 FPS with responsive touch interaction.
10. The experience contains no reward systems, competitive mechanics, or attention-maximizing design patterns.

At this point, the alphabet module becomes the reference implementation for all future educational content (numbers, phonics, shapes, colors, vocabulary, and reading), reusing the same lesson engine and interaction framework.