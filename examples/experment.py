import os
os.environ["MINEDOJO_HEADLESS"]="1"
import argparse
import numpy as np
from tqdm import tqdm

parser = argparse.ArgumentParser()
parser.add_argument('--llm_name', type=str, default='text-davinci-003', help='Name of the LLM')
parser.add_argument('--env_names', type=str, default='MinedojoCreative7-v0', help='Comma separated list of environments to run')

args = parser.parse_args()

LLM_name = args.llm_name

from unified_LLM_querying import get_query
query_model = get_query(LLM_name)

def compose_ingame_prompt(info, question, past_qa=[]):
    messages = [
    {"role": "system", "content" : "You’re a player trying to play the game."}
    ]
    
    if len(info['manual'])>0:
        messages.append({"role": "system", "content": info['manual']})

    if len(info['history'])>0:
        messages.append({"role": "system", "content": info['history']})

    messages.append({"role": "system", "content": "current step observation: {}".format(info['obs'])})

    if len(past_qa)>0:
        for q,a in past_qa:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})

    messages.append({"role": "user", "content": question})

    return messages, 2 # This is the index of the history, we will truncate the history if it is too long for LLM

questions=[
        "What is the best action to take? Let's think step by step, ",
        "Choose the best executable action from the list of all actions. Write the exact chosen action."
    ]

import gym
import smartplay
def run(env_name):
    env = gym.make("smartplay:{}".format(env_name))
    env_steps = env.default_steps
    num_iter = env.default_iter

    def match_act(output):
        inds = [(i, output.lower().index(act.lower())) for i, act in enumerate(env.action_list) if act.lower() in output.lower()]
        if len(inds)>0:
            # return the action with smallest index
            return sorted(inds, key=lambda x:x[1])[0][0]
        else:
            # print("LLM failed with output \"{}\", taking action 0...".format(output))
            return 0

    rewards = []
    steps = []
    progresses = []
    for eps in tqdm(range(num_iter), desc="Evaluating LLM {} on {}".format(LLM_name, env_name)):
        import wandb
        wandb.init(project="SmartPlay", config={"LLM": LLM_name, "env": env_name, "eps": eps, "num_iter": num_iter, "env_steps": env_steps})
        step = 0
        trajectories = []
        qa_history = []
        progress = [0]
        reward = 0
        rewards = []
        scores = []
        done=False

        columns=["Context", "Step", "OBS", "History", "Score", "Reward", "Total Score", "Total Reward"] + questions + ["Action"]
        wandb_table = wandb.Table(columns=columns)

        _, info = env.reset()
        
        while step < env_steps:

            new_row = [info['manual'], step, info['obs'], info['history'], info['score'], reward, sum(scores), sum(rewards)]
            wandb.log({"metric/total_reward".format(eps): sum(rewards), 
                       "metric/total_score".format(eps): sum(scores),
                       "metric/score".format(eps): info['score'],
                       "metric/reward".format(eps): reward,
                       })
            
            if done:
                break
            
            qa_history = []
            for question in questions:
                prompt = compose_ingame_prompt(info, question, qa_history)
                answer = query_model(*prompt)
                qa_history.append((question, answer))
                new_row.append(answer)
                answer_act = answer

            a = match_act(answer_act)
            new_row.append(env.action_list[a])
            _, reward, done, info = env.step(a)
            rewards.append(reward)
            scores.append(info['score'])

            step += 1
            wandb_table.add_data(*new_row)

        if not done:
            completion=0
        else:
            completion=info['completed']
        progresses.append(np.max(progress))
        wandb.log({"rollout/rollout".format(eps): wandb_table, 
                "final/total_reward":sum(rewards),
                "final/total_score":sum(scores),
                "final/completion":completion,
                "final/episodic_step":step,
                "final/eps":eps,
                })
        del wandb_table
        wandb.finish()

for env_name in args.env_names.split(','):
    run(env_name)
