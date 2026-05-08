We now have AgentLoop and CoreAgent two layer messages list. 

We need a prompt-cache friendly message injection into coreagent execution. Here is main
considerations: 

1. keep all static unchanged info in system message. each content block is XML formatted.

2. the more dynamic, the more tail placed in the message list.

3. DO NOT place memory/retrived knowledge as conversation message, which would pollute the dialogue semantics.

4. As seen in attached image, Loop messages are all a copy of CoreAgent messages except for the goal completion is generated outside CoreAgent thread (when synthesis required). So we can merge Loop messages into CoreAgent checkpoints messages in time line and eliminating the duplication. We should record the orginal coreAgent message ID in the thread in Loop messages to help dedup.

5. the system prompt is depicited in the image

6. Design a standard soothe user message format to contain memory and dynamic context info, such as

<MEMORY_AND_KNOWLEDGE>
</RETRIVED_MEMORY>
</RAG_DOCS>
</MEMORY_AND_KNOWLEDGE>

<USER_QUERY>
real user query
</USER_QUERY>

<CONTEXT_INFO>
current time stamp
</CONTEXT_INFO>