import React, { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Send, Sparkles } from 'lucide-react';
import type { BaseModelMeta, DesignBrief } from '../types/design.ts';
import {
  fetchAiChatHistory,
  generateAiImage,
  parseApiError,
  streamAiChat,
  type AiChatMessage,
  type GeneratedPatternImage,
} from '../services/apiClient.ts';

interface AISidebarProps {
  token: string | null;
  sessionId: number | null;
  brief: DesignBrief | null;
  baseModel: BaseModelMeta | null;
  onInsertImageToCanvas?: (payload: { imageUrl: string; prompt: string; imageId: number }) => void;
}

interface TextChatMessage {
  id: string;
  role: 'ai' | 'user';
  kind: 'text';
  content: string;
  pending?: boolean;
  createdAt?: string;
}

interface ImageResultMessage {
  id: string;
  role: 'ai';
  kind: 'image_result';
  content: string;
  images: GeneratedPatternImage[];
  pending?: boolean;
  createdAt?: string;
}

type ChatMessage = TextChatMessage | ImageResultMessage;

const extractImagePrompt = (input: string): string => {
  let prompt = input.trim();
  prompt = prompt.replace(/^(please\s+)?(help\s+me\s+)?(create|generate|render)\s*/i, '');
  prompt = prompt.replace(/\s*(image|pattern|texture|decal)\s*$/i, '');
  return prompt.trim() || input.trim();
};

const buildAutoStyleHint = (brief: DesignBrief | null, baseModel: BaseModelMeta | null): string | undefined => {
  const parts: string[] = [];
  if (brief?.styleKeywords?.length) {
    parts.push(`style keywords: ${brief.styleKeywords.slice(0, 4).join(', ')}`);
  }
  if (brief?.mainColors?.length) {
    parts.push(`main colors: ${brief.mainColors.slice(0, 3).join(', ')}`);
  }
  if (baseModel?.precisionLevel) {
    parts.push(`model precision: ${baseModel.precisionLevel}`);
  }
  return parts.length > 0 ? parts.join('; ') : undefined;
};

const toChatMessage = (message: AiChatMessage): ChatMessage => ({
  id: String(message.id),
  role: message.role === 'user' ? 'user' : 'ai',
  kind: 'text',
  content: message.content,
  createdAt: message.createdAt,
});

const AISidebar: React.FC<AISidebarProps> = ({ token, sessionId, brief, baseModel, onInsertImageToCanvas }) => {
  const [isOpen, setIsOpen] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sendingChat, setSendingChat] = useState(false);
  const [generatingImage, setGeneratingImage] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [generateImageChecked, setGenerateImageChecked] = useState(false);

  const contextTags = useMemo(() => {
    const tags: string[] = [];
    if (brief?.theme) {
      tags.push(`Theme: ${brief.theme}`);
    }
    if (brief?.styleKeywords && brief.styleKeywords.length > 0) {
      tags.push(`Style: ${brief.styleKeywords.slice(0, 2).join('/')}`);
    }
    if (baseModel) {
      tags.push(`Model: ${baseModel.sourceType}`);
      tags.push(`Precision: ${baseModel.precisionLevel}`);
    }
    return tags.slice(0, 4);
  }, [baseModel, brief]);

  useEffect(() => {
    if (!token || !sessionId) {
      setMessages([]);
      return;
    }

    let cancelled = false;
    const run = async () => {
      try {
        setLoadingHistory(true);
        setChatError(null);
        const history = await fetchAiChatHistory(token, { sessionId, limit: 40 });
        if (cancelled) {
          return;
        }
        setMessages(history.items.slice().reverse().map(toChatMessage));
      } catch (error) {
        if (!cancelled) {
          setChatError(parseApiError(error, 'Failed to load AI history.'));
        }
      } finally {
        if (!cancelled) {
          setLoadingHistory(false);
        }
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [sessionId, token]);

  const appendLocalMessage = (message: ChatMessage) => {
    setMessages((previous) => [...previous, message]);
  };

  const handleSendChat = async () => {
    const trimmed = chatInput.trim();
    if (trimmed.length === 0 || !token || !sessionId || sendingChat || generatingImage) {
      return;
    }

    const shouldGenerateImage = generateImageChecked;
    const imagePrompt = shouldGenerateImage ? extractImagePrompt(trimmed) : '';
    const autoStyleHint = shouldGenerateImage ? buildAutoStyleHint(brief, baseModel) : undefined;
    const now = Date.now();
    const userTempId = `local-user-${now}`;
    const aiTextTempId = `local-ai-text-${now}`;
    const aiImageTempId = `local-ai-image-${now}`;

    appendLocalMessage({ id: userTempId, role: 'user', kind: 'text', content: trimmed, pending: true });
    appendLocalMessage({ id: aiTextTempId, role: 'ai', kind: 'text', content: '', pending: true });
    if (shouldGenerateImage) {
      appendLocalMessage({
        id: aiImageTempId,
        role: 'ai',
        kind: 'image_result',
        content: 'Generating pattern assets...',
        images: [],
        pending: true,
      });
    }

    setChatInput('');
    setGenerateImageChecked(false);
    setChatError(null);
    setSendingChat(true);

    try {
      const result = await streamAiChat(
        token,
        {
          sessionId,
          message: trimmed,
          mode: shouldGenerateImage ? 'image' : 'creative',
        },
        {
          onChunk: (_delta, fullText) => {
            setMessages((previous) =>
              previous.map((item) =>
                item.id === aiTextTempId && item.kind === 'text'
                  ? {
                      ...item,
                      content: fullText,
                    }
                  : item,
              ),
            );
          },
          onDone: (assistantMessage) => {
            setMessages((previous) =>
              previous.map((item) => {
                if (item.id === userTempId && item.kind === 'text') {
                  return { ...item, pending: false };
                }
                if (item.id === aiTextTempId && item.kind === 'text') {
                  return {
                    id: String(assistantMessage.id),
                    role: 'ai',
                    kind: 'text',
                    content: assistantMessage.content,
                    pending: false,
                    createdAt: assistantMessage.createdAt,
                  };
                }
                return item;
              }),
            );
          },
          onError: (message) => {
            setChatError(message);
          },
        },
      );

      if (!result.assistantMessage) {
        let recoveredAssistant: AiChatMessage | null = null;
        if (result.fullText.trim().length === 0) {
          try {
            const history = await fetchAiChatHistory(token, { sessionId, limit: 12 });
            const minCreatedAt = now - 2 * 60 * 1000;
            recoveredAssistant =
              history.items.find(
                (item) => item.role === 'assistant' && new Date(item.createdAt).getTime() >= minCreatedAt,
              ) ?? null;
          } catch {
            recoveredAssistant = null;
          }
        }

        setMessages((previous) =>
          previous.map((item) => {
            if (item.id === userTempId && item.kind === 'text') {
              return { ...item, pending: false };
            }
            if (item.id === aiTextTempId && item.kind === 'text') {
              if (recoveredAssistant) {
                return {
                  id: String(recoveredAssistant.id),
                  role: 'ai',
                  kind: 'text',
                  content: recoveredAssistant.content,
                  pending: false,
                  createdAt: recoveredAssistant.createdAt,
                };
              }
              return {
                ...item,
                pending: false,
                content: result.fullText.trim() || 'AI 返回为空，请重试。',
              };
            }
            return item;
          }),
        );
      }

      if (shouldGenerateImage) {
        setGeneratingImage(true);
        try {
          const items = await generateAiImage(token, {
            sessionId,
            prompt: imagePrompt,
            styleHint: autoStyleHint,
          });
          setMessages((previous) =>
            previous.map((item) => {
              if (item.id !== aiImageTempId || item.kind !== 'image_result') {
                return item;
              }
              return {
                ...item,
                pending: false,
                content:
                  items.length > 0
                    ? `Generated ${items.length} image asset(s). You can insert any of them into the canvas.`
                    : 'Image generation completed, but no images were returned.',
                images: items,
                createdAt: new Date().toISOString(),
              };
            }),
          );
        } catch (error) {
          const message = parseApiError(error, 'Failed to generate image assets.');
          setChatError(message);
          setMessages((previous) =>
            previous.map((item) => {
              if (item.id !== aiImageTempId) {
                return item;
              }
              return {
                ...item,
                pending: false,
                content: `Image generation failed: ${message}`,
                images: [],
                createdAt: new Date().toISOString(),
              };
            }),
          );
        } finally {
          setGeneratingImage(false);
        }
      }
    } catch (error) {
      const message = parseApiError(error, 'Failed to send message.');
      setChatError(message);
      setMessages((previous) =>
        previous.map((item) => {
          if (item.id === userTempId && item.kind === 'text') {
            return { ...item, pending: false };
          }
          if (item.id === aiTextTempId && item.kind === 'text') {
            return { ...item, pending: false, content: `Request failed: ${message}` };
          }
          if (item.id === aiImageTempId && item.kind === 'image_result') {
            return {
              ...item,
              pending: false,
              content: `Image generation canceled: ${message}`,
              images: [],
            };
          }
          return item;
        }),
      );
    } finally {
      setSendingChat(false);
    }
  };

  return (
    <aside
      className={`relative border-r border-slate-200 bg-white transition-all duration-300 ${
        isOpen ? 'w-96' : 'w-0'
      }`}
    >
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        className="absolute -right-3 top-1/2 z-30 flex h-12 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition hover:text-slate-700"
      >
        {isOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
      </button>

      <div className={`flex h-full flex-col overflow-hidden ${isOpen ? 'opacity-100' : 'opacity-0'}`}>
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 p-4">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-blue-600 p-1.5 text-white">
              <Sparkles size={14} />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Creative + Pattern Agent
              </p>
              <p className="text-[10px] text-slate-500">Use checkbox to enable image generation for a message.</p>
            </div>
          </div>
        </div>

        <div className="border-b border-slate-100 p-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Context Tags</p>
          <div className="flex flex-wrap gap-2">
            {contextTags.length === 0 ? (
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-500">No context yet</span>
            ) : (
              contextTags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-700"
                >
                  {tag}
                </span>
              ))
            )}
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {loadingHistory ? <p className="text-xs text-slate-500">Loading history...</p> : null}
          {messages.length === 0 && !loadingHistory ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
              Try prompts like: "Suggest 3 palette directions for this train skin". Check "Generate image assets"
              when you want images.
            </p>
          ) : null}

          {messages.map((message) => (
            <div key={message.id} className={message.role === 'user' ? 'text-right' : 'text-left'}>
              {message.kind === 'text' ? (
                <div
                  className={`inline-block max-w-[92%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    message.role === 'user'
                      ? 'rounded-tr-none bg-slate-900 text-white'
                      : 'rounded-tl-none border border-slate-200 bg-slate-100 text-slate-700'
                  }`}
                >
                  {message.content.length > 0 ? message.content : '...'}
                </div>
              ) : (
                <div className="inline-block max-w-[92%] rounded-2xl rounded-tl-none border border-slate-200 bg-slate-100 px-3 py-2 text-left text-sm text-slate-700">
                  <p>{message.content}</p>
                  {!message.pending && message.images.length > 0 ? (
                    <div className="mt-3 grid grid-cols-1 gap-2">
                      {message.images.map((item) => (
                        <div key={item.id} className="rounded-lg border border-slate-200 bg-white p-2">
                          <img
                            src={item.imageUrl}
                            alt={`generated-${item.id}`}
                            className="h-28 w-full rounded-md border border-slate-200 object-cover"
                          />
                          <p className="mt-2 line-clamp-2 text-[11px] text-slate-600">
                            {item.revisedPrompt ?? item.prompt}
                          </p>
                          <button
                            type="button"
                            onClick={() =>
                              onInsertImageToCanvas?.({
                                imageUrl: item.imageUrl,
                                prompt: item.revisedPrompt ?? item.prompt,
                                imageId: item.id,
                              })
                            }
                            className="mt-2 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700"
                          >
                            Insert To Canvas
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
              {message.pending ? <p className="mt-1 text-[10px] text-slate-400">Processing...</p> : null}
            </div>
          ))}

          {chatError ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{chatError}</p>
          ) : null}
        </div>

        <div className="border-t border-slate-200 p-4">
          <label className="mb-2 flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={generateImageChecked}
              onChange={(event) => setGenerateImageChecked(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              disabled={sendingChat || generatingImage}
            />
            Generate image assets
          </label>
          <div className="relative">
            <textarea
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void handleSendChat();
                }
              }}
              placeholder='Type your request. Example: "Suggest 3 palette directions for this train skin".'
              className="min-h-[92px] w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 pr-10 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:bg-white"
            />
            <button
              type="button"
              onClick={() => {
                void handleSendChat();
              }}
              disabled={sendingChat || generatingImage}
              className="absolute bottom-2 right-2 rounded-lg bg-blue-600 p-2 text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              <Send size={15} />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
};

export default AISidebar;


